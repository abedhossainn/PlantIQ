"""Per-document optimization log capture for real-time SSE streaming.

Architecture:
- ``OptimizationLogHandler`` is a stdlib ``logging.Handler`` that captures
  records emitted from the pipeline thread during Stage 10 and forwards them
  to ``OptimizationLogManager`` via ``loop.call_soon_threadsafe`` so the
  asyncio event loop is never touched from the worker thread.
- ``OptimizationLogManager`` maintains an in-memory replay buffer and a set
  of per-document asyncio subscriber queues consumed by the SSE endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_EMOJI_PREFIX_RE = re.compile(r"^[\W_]*(?:[\u2190-\u2BFF\u2600-\u27BF\uFE0E\uFE0F\U0001F300-\U0001FAFF]+\s*)+")
_SEGMENT_FRACTION_RE = re.compile(r"\bsegment\s+(?P<current>\d+)\s*/\s*(?P<total>\d+)\b", re.IGNORECASE)
_GENERATION_PROGRESS_RE = re.compile(
    r"^Generate output:\s*(?P<percent>-?\d+)%\s*\((?P<generated>\d+)\s*/\s*(?P<target>\d+)\s*tokens,\s*(?P<minutes>\d+):(?P<seconds>\d{2})\s*elapsed\)$",
    re.IGNORECASE,
)
_GENERATION_COMPLETE_RE = re.compile(
    r"^Generation complete for\s+segment\s+(?P<current>\d+)\s*/\s*(?P<total>\d+)\s*\((?P<generated>\d+)\s*tokens in\s*(?P<elapsed>[\d.]+)s\)",
    re.IGNORECASE,
)


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _to_elapsed_seconds(minutes: int, seconds: int) -> int:
    normalized_seconds = max(0, int(seconds))
    normalized_minutes = max(0, int(minutes))
    return (normalized_minutes * 60) + normalized_seconds


def _derive_overall_progress_percent(
    *,
    current_segment: Optional[int],
    total_segments: Optional[int],
    segment_progress_percent: int,
) -> int:
    if current_segment is None or total_segments is None or total_segments <= 0:
        return _clamp_percent(segment_progress_percent)

    normalized_current = max(1, min(int(current_segment), int(total_segments)))
    normalized_segment_progress = _clamp_percent(segment_progress_percent)
    overall = ((normalized_current - 1) + (normalized_segment_progress / 100.0)) / int(total_segments)
    return _clamp_percent(int(round(overall * 100)))


def _build_progress_payload(
    *,
    document_id: str,
    timestamp: str,
    state: dict,
) -> dict:
    current_segment = state.get("current_segment")
    total_segments = state.get("total_segments")
    segment_progress_percent = _clamp_percent(int(state.get("segment_progress_percent", 0)))
    overall_progress_percent = _derive_overall_progress_percent(
        current_segment=current_segment,
        total_segments=total_segments,
        segment_progress_percent=segment_progress_percent,
    )

    label = (
        f"Segment {current_segment}/{total_segments}"
        if current_segment is not None and total_segments is not None
        else "Segment generation"
    )

    return {
        "event": "progress",
        "timestamp": timestamp,
        "document_id": document_id,
        "phase": "segment-generation",
        "current_segment": current_segment,
        "total_segments": total_segments,
        "segment_progress_percent": segment_progress_percent,
        "overall_progress_percent": overall_progress_percent,
        "tokens_generated": state.get("tokens_generated"),
        "tokens_target": state.get("tokens_target"),
        "elapsed_seconds": state.get("elapsed_seconds"),
        "label": label,
    }


def _extract_progress_payload(document_id: str, entry: dict, state: dict) -> Optional[dict]:
    message = str(entry.get("message") or "").strip()
    if not message:
        return None

    segment_match = _SEGMENT_FRACTION_RE.search(message)
    if segment_match:
        state["current_segment"] = int(segment_match.group("current"))
        state["total_segments"] = int(segment_match.group("total"))

    progress_match = _GENERATION_PROGRESS_RE.match(message)
    if progress_match:
        state["segment_progress_percent"] = _clamp_percent(int(progress_match.group("percent")))
        state["tokens_generated"] = int(progress_match.group("generated"))
        state["tokens_target"] = int(progress_match.group("target"))
        state["elapsed_seconds"] = _to_elapsed_seconds(
            int(progress_match.group("minutes")),
            int(progress_match.group("seconds")),
        )
        return _build_progress_payload(
            document_id=document_id,
            timestamp=str(entry.get("timestamp") or _utc_now_iso()),
            state=state,
        )

    complete_match = _GENERATION_COMPLETE_RE.match(message)
    if complete_match:
        state["current_segment"] = int(complete_match.group("current"))
        state["total_segments"] = int(complete_match.group("total"))
        state["segment_progress_percent"] = 100
        state["tokens_generated"] = int(complete_match.group("generated"))
        state["elapsed_seconds"] = max(0, int(round(float(complete_match.group("elapsed")))))
        if state.get("tokens_target") is None:
            state["tokens_target"] = state.get("tokens_generated")
        return _build_progress_payload(
            document_id=document_id,
            timestamp=str(entry.get("timestamp") or _utc_now_iso()),
            state=state,
        )

    return None


def normalize_optimization_message(message: str) -> str | None:
    """Normalize optimization log text for the live terminal view.

    Removes decorative noise and rewrites internal/debug-oriented messages into
    concise deployment-style status lines.
    """
    text = (message or "").strip()
    if not text:
        return None

    text = _EMOJI_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)

    if re.fullmatch(r"=+", text):
        return None

    replacements: list[tuple[str, str | None]] = [
        (r"^STAGE 10: .*", None),
        (r"^This will take .*", None),
        (r"^Sending to .* for RAG optimization\.\.\.$", None),
        (r"^Text Reformatting \(model=.*\)$", None),
        (r"^Text Reformatting complete \((.+)\)$", r"Job completed in \1"),
        (r"^Optimization started$", "Starting job"),
        (r"^Load Tokenizer$", "Initialize tokenizer"),
        (r"^Load Tokenizer complete \((.+)\)$", r"Tokenizer ready in \1"),
        (r"^Load Model$", "Initialize model"),
        (r"^Load Model complete \((.+)\)$", r"Model ready in \1"),
        (r"^Generate Response \(chars=(.+)\)$", r"Prepare generation request (\1 chars)"),
        (r"^Generating \((.+) max tokens\)\.\.\.$", r"Generate output (up to \1 tokens)"),
        (r"^Generate Response complete \((.+)\)$", r"Generation finished in \1"),
        (r"^Generation progress: (.+)$", r"Generate output: \1"),
        (r"^Unloading model resources\.\.\.$", "Finalize output"),
        (r"^Model resources released$", None),
        (r"^Parse Response$", "Validate output"),
        (r"^Parse Response complete \((.+)\)$", r"Validation finished in \1"),
        (r"^JSON parsed and normalized successfully$", "Output validated"),
        (r"^Using built-in reformatter prompt fallback because .*", "Using fallback prompt"),
        (r"^Structured JSON response could not be recovered; using deterministic optimization-prep synthesis$", "Fallback output generated"),
        (r"^Generation unavailable; using deterministic optimization-prep synthesis: (.+)$", "Generation unavailable; using fallback output"),
        (r"^Insufficient free GPU memory after model load \((.+) available\); using deterministic optimization-prep synthesis$", r"Insufficient GPU memory (\1 available); using fallback output"),
        (r"^Saving optimization artifacts$", "Write artifacts"),
        (r"^Optimized artifacts written in (.+)$", r"Artifacts written in \1"),
        (r"^Reformatting complete$", "Artifacts ready"),
        (r"^Optimization completed in (.+)$", r"Job completed in \1"),
        (r"^JSON: .*$", None),
        (r"^Markdown: .*$", None),
    ]

    for pattern, replacement in replacements:
        if re.match(pattern, text):
            if replacement is None:
                return None
            return re.sub(pattern, replacement, text)

    return text


class OptimizationLogManager:
    """In-memory log buffer + subscriber queues for optimization log streaming."""

    # Per-document rolling replay buffer (up to 500 lines)
    _buffers: dict[str, deque] = {}
    # Active SSE subscriber queues per document
    _queues: dict[str, list[asyncio.Queue]] = {}
    # Whether optimization has finished for a document
    _done: dict[str, bool] = {}
    # Final terminal status for completed streams
    _done_status: dict[str, str] = {}
    # Latest structured progress snapshot per document
    _progress_state: dict[str, dict] = {}

    @classmethod
    def start(cls, document_id: str) -> None:
        """Called when optimization begins. Resets buffer; preserves existing subscribers."""
        cls._buffers[document_id] = deque(maxlen=500)
        cls._done[document_id] = False
        cls._done_status.pop(document_id, None)
        cls._progress_state.pop(document_id, None)
        # Preserve any subscriber queues that connected before start()
        if document_id not in cls._queues:
            cls._queues[document_id] = []

    @classmethod
    def publish_line(cls, document_id: str, entry: dict) -> None:
        """Push a log entry to the buffer and all active subscribers.

        Safe to call from the asyncio event loop thread (via call_soon_threadsafe).
        """
        buf = cls._buffers.get(document_id)
        if buf is not None:
            buf.append(entry)
        state = cls._progress_state.setdefault(document_id, {})
        progress_payload = _extract_progress_payload(document_id, entry, state)
        if progress_payload is not None:
            cls._progress_state[document_id] = progress_payload
        for q in list(cls._queues.get(document_id, [])):
            try:
                q.put_nowait(("log", entry))
            except asyncio.QueueFull:
                pass
            if progress_payload is not None:
                try:
                    q.put_nowait(("progress", progress_payload))
                except asyncio.QueueFull:
                    pass

    @classmethod
    def close(cls, document_id: str, final_status: str = "optimization-complete") -> None:
        """Signal end-of-stream to all subscribers."""
        cls._done[document_id] = True
        cls._done_status[document_id] = final_status
        for q in list(cls._queues.get(document_id, [])):
            try:
                q.put_nowait(("done", {"status": final_status}))
            except asyncio.QueueFull:
                pass
        cls._queues.pop(document_id, None)

    @classmethod
    def get_final_status(cls, document_id: str) -> Optional[str]:
        return cls._done_status.get(document_id)

    @classmethod
    def get_progress_snapshot(cls, document_id: str) -> Optional[dict]:
        snapshot = cls._progress_state.get(document_id)
        if snapshot is None:
            return None
        return dict(snapshot)

    @classmethod
    def subscribe(cls, document_id: str) -> tuple[list[dict], Optional[asyncio.Queue]]:
        """Return (buffer_snapshot, live_queue).

        ``live_queue`` is ``None`` if the optimization is already finished,
        in which case only the replay buffer is returned.
        """
        buffer = list(cls._buffers.get(document_id, []))
        if cls._done.get(document_id, False):
            return buffer, None
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        cls._queues.setdefault(document_id, []).append(q)
        return buffer, q

    @classmethod
    def unsubscribe(cls, document_id: str, q: asyncio.Queue) -> None:
        queues = cls._queues.get(document_id, [])
        try:
            queues.remove(q)
        except ValueError:
            pass

    @classmethod
    def clear_document(cls, document_id: str) -> None:
        """Remove all in-memory log state for a document."""
        cls._buffers.pop(document_id, None)
        cls._queues.pop(document_id, None)
        cls._done.pop(document_id, None)
        cls._done_status.pop(document_id, None)
        cls._progress_state.pop(document_id, None)


class OptimizationLogHandler(logging.Handler):
    """Logging handler that captures records from the thread-pool worker.

    Uses ``loop.call_soon_threadsafe`` to safely publish to asyncio queues.
    """

    def __init__(self, document_id: str, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self.document_id = document_id
        self.loop = loop
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            normalized_message = normalize_optimization_message(msg)
            if normalized_message is None:
                return
            level = str(record.levelname or "INFO").upper()
            if level not in {"INFO", "WARNING", "ERROR"}:
                level = "ERROR" if level in {"CRITICAL", "FATAL"} else "INFO"
            entry = {
                "timestamp": _utc_now_iso(),
                "level": level,
                "message": normalized_message,
            }
            self.loop.call_soon_threadsafe(
                OptimizationLogManager.publish_line, self.document_id, entry
            )
        except Exception:
            pass
