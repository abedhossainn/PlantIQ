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

    @classmethod
    def start(cls, document_id: str) -> None:
        """Called when optimization begins. Resets buffer; preserves existing subscribers."""
        cls._buffers[document_id] = deque(maxlen=500)
        cls._done[document_id] = False
        cls._done_status.pop(document_id, None)
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
        for q in list(cls._queues.get(document_id, [])):
            try:
                q.put_nowait(("log", entry))
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
