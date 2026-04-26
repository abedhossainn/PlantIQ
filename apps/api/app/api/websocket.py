"""
WebSocket API Endpoints.

Real-time WebSocket channels for pipeline status and chat streaming.
"""
import logging
import json
import asyncio
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
from sqlalchemy import text

from ..core.config import settings
from ..core.websocket import get_connection_manager
from ..core.security import verify_ws_token
from ..models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])


async def _send_ws_error(websocket: WebSocket, error: str, *, operation: Optional[str] = None) -> None:
    """Send a structured websocket error payload."""
    payload = {"type": "error", "error": error}
    if operation is not None:
        payload["operation"] = operation
    await websocket.send_json(payload)


async def _send_ws_connected(websocket: WebSocket, *, channel: str, message: str) -> None:
    await websocket.send_json(
        {
            "type": "connected",
            "channel": channel,
            "message": message,
        }
    )


async def _receive_or_heartbeat(websocket: WebSocket) -> str | None:
    try:
        return await asyncio.wait_for(
            websocket.receive_text(),
            timeout=float(settings.WS_HEARTBEAT_INTERVAL),
        )
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "heartbeat"})
        return None


def _parse_json_message_or_none(data: str) -> dict | None:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON from client: %s", data[:100])
        return None


async def _authorize_pipeline_socket(
    websocket: WebSocket,
    document_id: str,
    token: Optional[str],
) -> tuple[uuid.UUID, str] | None:
    auth_result = await verify_ws_token(token)
    if not auth_result:
        await websocket.close(code=403, reason="Unauthorized")
        return None

    user_id, user_role = auth_result
    if user_role not in {"admin", "plantig_admin"}:
        await websocket.close(code=403, reason="Forbidden: Pipeline updates require admin access")
        return None

    has_access = await check_document_access(document_id, user_id, user_role)
    if not has_access:
        await websocket.close(code=403, reason="Forbidden: No access to this document")
        return None

    return user_id, user_role


async def _authorize_chat_socket(
    websocket: WebSocket,
    conversation_id: str,
    token: Optional[str],
) -> tuple[uuid.UUID, str] | None:
    auth_result = await verify_ws_token(token)
    if not auth_result:
        await websocket.close(code=403, reason="Unauthorized")
        return None

    user_id, user_role = auth_result
    has_access = await check_conversation_access(conversation_id, user_id)
    if not has_access:
        await websocket.close(code=403, reason="Forbidden: No access to this conversation")
        return None

    return user_id, user_role


async def _run_pipeline_ws_loop(websocket: WebSocket) -> None:
    while True:
        data = await _receive_or_heartbeat(websocket)
        if data is None:
            continue
        message = _parse_json_message_or_none(data)
        if message is None:
            continue
        if message.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


async def _handle_chat_ws_message(websocket: WebSocket, conversation_id: str, message: dict) -> None:
    message_type = message.get("type")
    if message_type == "ping":
        await websocket.send_json({"type": "pong"})
        return

    if message_type == "query":
        query_preview = str(message.get("content") or "")[:50]
        logger.info("Received unsupported websocket chat query: %s...", query_preview)
        await _send_ws_error(
            websocket,
            "Query processing via WebSocket is not yet implemented. Use POST /api/v1/chat/stream instead.",
            operation="query",
        )
        return

    if message_type == "cancel":
        logger.info("Received unsupported websocket cancel request for %s", conversation_id)
        await _send_ws_error(
            websocket,
            "Generation cancellation via WebSocket is not supported for this endpoint.",
            operation="cancel",
        )


async def _run_chat_ws_loop(websocket: WebSocket, conversation_id: str) -> None:
    while True:
        data = await _receive_or_heartbeat(websocket)
        if data is None:
            continue
        message = _parse_json_message_or_none(data)
        if message is None:
            continue
        await _handle_chat_ws_message(websocket, conversation_id, message)


async def check_document_access(document_id: str, user_id: uuid.UUID, user_role: str) -> bool:
    """
    Check if user has access to document.

    Args:
        document_id: Document UUID
        user_id: User UUID from JWT
        user_role: User role from JWT (admin/user)

    Returns:
        True if user has access, False otherwise
    """
    async with AsyncSessionLocal() as session:
        try:
            # Set role context for RLS
            role_map = {
                "admin": "plantig_admin",
                "user": "plantig_user",
                "plantig_admin": "plantig_admin",
                "plantig_user": "plantig_user",
                "plantig_reviewer": "plantig_reviewer",
            }
            db_role = role_map.get(user_role, "plantig_user")
            await session.execute(text(f"SET LOCAL ROLE {db_role}"))
            claims_json = json.dumps({"sub": str(user_id), "role": user_role})
            await session.execute(
                text("SELECT set_config('request.jwt.claims', :claims, true)"),
                {"claims": claims_json},
            )
            
            # Check if document exists and user has access (RLS will filter)
            result = await session.execute(
                text("SELECT id FROM documents WHERE id = :doc_id"),
                {"doc_id": document_id}
            )
            return result.fetchone() is not None
        except Exception as exc:
            logger.error("Error checking document access: %s", exc)
            return False
        finally:
            try:
                await session.execute(text("RESET ROLE"))
            except Exception:
                pass


async def check_conversation_access(conversation_id: str, user_id: uuid.UUID) -> bool:
    """
    Check if user owns conversation.
    
    Args:
        conversation_id: Conversation UUID
        user_id: User UUID from JWT
        
    Returns:
        True if user owns conversation, False otherwise
    """
    async with AsyncSessionLocal() as session:
        try:
            # Check conversation ownership
            result = await session.execute(
                text("SELECT id FROM conversations WHERE id = :conv_id AND user_id = :user_id"),
                {"conv_id": conversation_id, "user_id": str(user_id)}
            )
            return result.fetchone() is not None
        except Exception as exc:
            logger.error("Error checking conversation access: %s", exc)
            return False


@router.websocket("/pipeline/{document_id}")
async def pipeline_status_websocket(
    websocket: WebSocket,
    document_id: str,
    token: Optional[str] = Query(None),
):
    """
    WebSocket channel for real-time pipeline status updates.
    
    URL: ws://backend:8000/ws/pipeline/{document_id}?token=<jwt>
    
    SECURITY: Admin-only channel for pipeline orchestration updates.
    
    Messages from server:
    - progress: {"type": "progress", "document_id": "...", "stage": "...", "progress": 45, "message": "..."}
    - stage-complete: {"type": "stage-complete", "document_id": "...", "stage": "...", "duration": 4235}
    - error: {"type": "error", "document_id": "...", "stage": "...", "error": "..."}
    - complete: {"type": "complete", "document_id": "...", "status": "...", "artifacts": [...]}
    
    Client sends:
    - ping: {"type": "ping"} -> server responds with pong
    """
    auth_result = await _authorize_pipeline_socket(websocket, document_id, token)
    if auth_result is None:
        return
    
    manager = get_connection_manager()
    channel = f"pipeline:{document_id}"
    
    await manager.connect(websocket, channel)
    
    try:
        await _send_ws_connected(
            websocket,
            channel=channel,
            message=f"Connected to pipeline status for document {document_id}",
        )
        await _run_pipeline_ws_loop(websocket)
    except WebSocketDisconnect:
        logger.info("Client disconnected from %s", channel)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        await manager.disconnect(websocket, channel)


@router.websocket("/chat/{conversation_id}")
async def chat_streaming_websocket(
    websocket: WebSocket,
    conversation_id: str,
    token: Optional[str] = Query(None),
):
    """
    WebSocket channel for real-time chat streaming.
    
    URL: ws://backend:8000/ws/chat/{conversation_id}?token=<jwt>
    
    SECURITY: Verifies user owns conversation.
    
    Messages from server:
    - token: {"type": "token", "content": "...", "conversation_id": "...", "message_id": "..."}
    - citation: {"type": "citation", "citation": {...}}
    - complete: {"type": "complete", "message_id": "...", "citations": [...]}
    - error: {"type": "error", "error": "..."}
    
    Messages from client:
    - query: {"type": "query", "content": "What is LNG density?"}
    - cancel: {"type": "cancel"} -> cancel current generation
    - ping: {"type": "ping"} -> server responds with pong
    """
    auth_result = await _authorize_chat_socket(websocket, conversation_id, token)
    if auth_result is None:
        return
    
    manager = get_connection_manager()
    channel = f"chat:{conversation_id}"
    
    await manager.connect(websocket, channel)
    
    try:
        await _send_ws_connected(
            websocket,
            channel=channel,
            message=f"Connected to chat stream for conversation {conversation_id}",
        )
        await _run_chat_ws_loop(websocket, conversation_id)
    except WebSocketDisconnect:
        logger.info("Client disconnected from %s", channel)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        await manager.disconnect(websocket, channel)
