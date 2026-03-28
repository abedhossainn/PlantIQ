"""
WebSocket API Endpoints.

Real-time WebSocket channels for pipeline status and chat streaming.
"""
import logging
import json
import asyncio
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Optional
from sqlalchemy import text

from ..core.websocket import get_connection_manager
from ..core.security import verify_ws_token
from ..models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])


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
            }
            db_role = role_map.get(user_role, "plantig_user")
            await session.execute(text(f"SET LOCAL ROLE {db_role}"))
            
            # Check if document exists and user has access (RLS will filter)
            result = await session.execute(
                text("SELECT id FROM documents WHERE id = :doc_id"),
                {"doc_id": document_id}
            )
            return result.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking document access: {e}")
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
        except Exception as e:
            logger.error(f"Error checking conversation access: {e}")
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
    # Verify authentication
    auth_result = await verify_ws_token(token)
    if not auth_result:
        await websocket.close(code=403, reason="Unauthorized")
        return
    
    user_id, user_role = auth_result

    if user_role != "admin":
        await websocket.close(code=403, reason="Forbidden: Pipeline updates require admin access")
        return

    # SECURITY FIX: Check document access authorization
    has_access = await check_document_access(document_id, user_id, user_role)
    if not has_access:
        await websocket.close(code=403, reason="Forbidden: No access to this document")
        return
    
    manager = get_connection_manager()
    channel = f"pipeline:{document_id}"
    
    await manager.connect(websocket, channel)
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "channel": channel,
            "message": f"Connected to pipeline status for document {document_id}"
        })
        
        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for messages from client (with timeout for heartbeat)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                
                try:
                    message = json.loads(data)
                    
                    # Handle ping/pong for keepalive
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                        
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from client: {data[:100]}")
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from {channel}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
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
    # Verify authentication
    auth_result = await verify_ws_token(token)
    if not auth_result:
        await websocket.close(code=403, reason="Unauthorized")
        return
    
    user_id, user_role = auth_result
    
    # SECURITY FIX: Check conversation ownership
    has_access = await check_conversation_access(conversation_id, user_id)
    if not has_access:
        await websocket.close(code=403, reason="Forbidden: No access to this conversation")
        return
    
    manager = get_connection_manager()
    channel = f"chat:{conversation_id}"
    
    await manager.connect(websocket, channel)
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "channel": channel,
            "message": f"Connected to chat stream for conversation {conversation_id}"
        })
        
        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for messages from client
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                
                try:
                    message = json.loads(data)
                    message_type = message.get("type")
                    
                    if message_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    
                    elif message_type == "query":
                        # Handle query message
                        # TODO: Process query through ChatService
                        logger.info(f"Received query: {message.get('content')[:50]}...")
                        await websocket.send_json({
                            "type": "error",
                            "error": "Query processing via WebSocket not yet implemented. Use POST /api/v1/chat/stream instead."
                        })
                    
                    elif message_type == "cancel":
                        # TODO: Implement generation cancellation
                        logger.info("Cancel request received")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from client: {data[:100]}")
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from {channel}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket, channel)
