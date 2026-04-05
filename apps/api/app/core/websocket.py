"""
WebSocket Manager - Handle WebSocket connections and message broadcasting.

Manages WebSocket connections for pipeline status and chat streaming.
"""
import logging
import asyncio
from typing import Dict, Set, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections for real-time data delivery.
    
    Supports channel-based broadcasting: multiple clients subscribe to the same
    document/topic and receive simultaneous updates (e.g., pipeline progress, chat tokens).
    Thread-safe for concurrent connections and disconnections.
    """
    
    def __init__(self):
        # Active connections by channel
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, channel: str):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        
        async with self._lock:
            if channel not in self.active_connections:
                self.active_connections[channel] = set()
            self.active_connections[channel].add(websocket)
        
        logger.info("Client connected to channel: %s", channel)
    
    async def disconnect(self, websocket: WebSocket, channel: str):
        """Remove a WebSocket connection."""
        async with self._lock:
            if channel in self.active_connections:
                self.active_connections[channel].discard(websocket)
                
                # Clean up empty channels
                if not self.active_connections[channel]:
                    del self.active_connections[channel]
        
            logger.info("Client disconnected from channel: %s", channel)
    
    async def send_message(self, channel: str, message: dict):
        """
        Send message to all connections in a channel.
        
        Args:
            channel: Channel identifier
            message: Message dict to send as JSON
        """
        async with self._lock:
            if channel not in self.active_connections:
                return
            
            # Get connections for this channel
            connections = self.active_connections[channel].copy()
        
        # Send to all connections (outside lock to avoid deadlock)
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as exc:
                logger.error("Error sending message: %s", exc)
                disconnected.append(websocket)
        
        # Remove disconnected clients
        if disconnected:
            async with self._lock:
                if channel in self.active_connections:
                    for ws in disconnected:
                        self.active_connections[channel].discard(ws)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connections."""
        async with self._lock:
            all_connections = set()
            for connections in self.active_connections.values():
                all_connections.update(connections)
        
        disconnected = []
        for websocket in all_connections:
            try:
                await websocket.send_json(message)
            except Exception as exc:
                logger.error("Error broadcasting message: %s", exc)
                disconnected.append(websocket)
        
        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                for channel, connections in list(self.active_connections.items()):
                    for ws in disconnected:
                        connections.discard(ws)
                    if not connections:
                        del self.active_connections[channel]
    
    def get_active_connections_count(self, channel: Optional[str] = None) -> int:
        """Get count of active connections."""
        if channel:
            return len(self.active_connections.get(channel, set()))
        return sum(len(conns) for conns in self.active_connections.values())


# Global connection manager
manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Get global connection manager instance."""
    return manager
