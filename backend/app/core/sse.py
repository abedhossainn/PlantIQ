"""Utilities for stable Server-Sent Events responses."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse
from pydantic import BaseModel


SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def encode_sse_event(payload: BaseModel | dict[str, Any], *, event_id: str | None = None) -> str:
    """Encode a payload as a single SSE event."""
    if isinstance(payload, BaseModel):
        body = payload.model_dump(mode="json", exclude_none=True)
    else:
        body = {
            key: value
            for key, value in payload.items()
            if value is not None
        }

    event_name = body.get("event", "message")
    json_payload = json.dumps(body, ensure_ascii=False)

    lines = [f"event: {event_name}"]
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json_payload}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def create_sse_response(event_stream: AsyncIterator[str]) -> StreamingResponse:
    """Create a StreamingResponse configured for SSE delivery."""
    return StreamingResponse(
        event_stream,
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )