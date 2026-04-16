"""WebSocket connection manager for chat."""

import logging
from typing import Dict, List, Set
from uuid import UUID

from starlette.websockets import WebSocket


logger = logging.getLogger(__name__)


class ChatConnectionManager:
    """Manages WebSocket connections for chat rooms."""
    
    def __init__(self):
        # room_id -> set of websockets
        self._rooms: Dict[str, Set[WebSocket]] = {}
        # user_id -> list of (room_id, websocket)
        self._user_connections: Dict[str, List[tuple]] = {}
    
    async def connect(self, websocket: WebSocket, room_id: str, user_id: str) -> None:
        """Accept connection and register it."""
        await websocket.accept()
        
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(websocket)
        
        if user_id not in self._user_connections:
            self._user_connections[user_id] = []
        self._user_connections[user_id].append((room_id, websocket))
        
        logger.debug("User %s connected to room %s", user_id, room_id)
    
    def disconnect(self, websocket: WebSocket, room_id: str, user_id: str) -> None:
        """Remove connection from registry."""
        if room_id in self._rooms:
            self._rooms[room_id].discard(websocket)
            if not self._rooms[room_id]:
                del self._rooms[room_id]
        
        if user_id in self._user_connections:
            self._user_connections[user_id] = [
                conn for conn in self._user_connections[user_id]
                if conn[1] != websocket
            ]
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        
        logger.debug("User %s disconnected from room %s", user_id, room_id)
    
    async def broadcast_to_room(
        self,
        room_id: str,
        message: dict,
        exclude: WebSocket = None
    ) -> None:
        """Broadcast a JSON message to all connections in a room."""
        if room_id not in self._rooms:
            return
        
        disconnected = []
        for ws in self._rooms[room_id]:
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning("Failed to send message to websocket: %s", e)
                disconnected.append(ws)
        
        # Clean up dead connections
        for ws in disconnected:
            self._rooms[room_id].discard(ws)
    
    async def send_personal_message(
        self,
        websocket: WebSocket,
        message: dict
    ) -> None:
        """Send a JSON message to a single websocket."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning("Failed to send personal message: %s", e)
    
    def get_room_connections(self, room_id: str) -> int:
        """Get number of active connections in a room."""
        return len(self._rooms.get(room_id, set()))
    
    def is_user_online(self, user_id: str) -> bool:
        """Check if a user has any active websocket connections."""
        return user_id in self._user_connections and len(self._user_connections[user_id]) > 0


# Global singleton instance
chat_manager = ChatConnectionManager()
