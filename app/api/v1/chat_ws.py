"""Chat WebSocket Router.

Real-time bidirectional messaging for chat rooms.
"""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.connection_manager import chat_manager
from app.core.security import jwt_auth_service
from app.services.chat_service import ChatService, get_chat_service
from app.db.session import async_session


logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat-websocket"])


async def _authenticate_websocket(websocket: WebSocket) -> dict:
    """Extract and validate JWT token from websocket query params."""
    token = websocket.query_params.get("token")
    
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        raise ValueError("Missing token")
    
    try:
        payload = jwt_auth_service.verify_token(token, expected_type="access")
        return payload
    except ExpiredSignatureError:
        await websocket.close(code=4001, reason="Token expired")
        raise
    except InvalidTokenError as e:
        await websocket.close(code=4001, reason=f"Invalid token: {e}")
        raise


@router.websocket("/ws/chat/{room_id}")
async def chat_websocket(websocket: WebSocket, room_id: str):
    """
    WebSocket endpoint for real-time chat.
    
    **Connection URL:**
    ```
    ws://localhost:8000/ws/chat/{room_id}?token=<jwt_access_token>
    ```
    
    **Authentication:**
    Pass the JWT access token as a `token` query parameter.
    
    **Message Protocol (JSON):**
    
    Client → Server:
    ```json
    {"type": "message", "content": "Halo admin"}
    ```
    
    Server → Client (broadcast):
    ```json
    {
      "type": "message",
      "id": "uuid",
      "room_id": "uuid",
      "sender_id": "uuid",
      "content": "Halo admin",
      "created_at": "2026-04-16T10:00:00+00:00"
    }
    ```
    
    Typing indicator:
    ```json
    {"type": "typing"}
    ```
    """
    # Authenticate
    try:
        payload = await _authenticate_websocket(websocket)
    except ValueError:
        return
    
    sub = payload.get("sub")
    role = payload.get("role")
    
    if not sub:
        await websocket.close(code=4001, reason="Invalid token payload")
        return
    
    try:
        user_id = UUID(sub)
    except ValueError:
        await websocket.close(code=4001, reason="Invalid user ID")
        return
    
    # Validate room_id
    try:
        room_uuid = UUID(room_id)
    except ValueError:
        await websocket.close(code=4002, reason="Invalid room ID")
        return
    
    async with async_session() as db:
        chat_service = get_chat_service(db)
        
        # Verify room exists and user is a participant (or admin)
        is_admin = role == "admin"
        room = await chat_service.repo.get_room_by_id(room_uuid)
        
        if not room:
            await websocket.close(code=4004, reason="Room not found")
            return
        
        if not is_admin and not await chat_service.repo.is_user_in_room(room_uuid, user_id):
            await websocket.close(code=4003, reason="Not a room participant")
            return
        
        # Auto-join admin if not already in room
        if is_admin and not await chat_service.repo.is_user_in_room(room_uuid, user_id):
            await chat_service.join_room(room_uuid, user_id)
        
        # Register connection
        await chat_manager.connect(websocket, room_id, str(user_id))
        
        # Notify room that user joined
        await chat_manager.broadcast_to_room(
            room_id,
            {
                "type": "system",
                "event": "user_joined",
                "room_id": room_id,
                "user_id": str(user_id),
            },
            exclude=websocket
        )
    
    try:
        while True:
            data = await websocket.receive_text()
            
            try:
                payload_msg = json.loads(data)
            except json.JSONDecodeError:
                await chat_manager.send_personal_message(
                    websocket,
                    {"type": "error", "detail": "Invalid JSON"}
                )
                continue
            
            msg_type = payload_msg.get("type")
            
            if msg_type == "message":
                content = payload_msg.get("content", "").strip()
                if not content:
                    await chat_manager.send_personal_message(
                        websocket,
                        {"type": "error", "detail": "Message content cannot be empty"}
                    )
                    continue
                
                async with async_session() as db:
                    chat_service = get_chat_service(db)
                    try:
                        await chat_service.send_message(
                            room_id=room_uuid,
                            sender_id=user_id,
                            content=content
                        )
                    except Exception as e:
                        logger.error("Error sending message: %s", e)
                        await chat_manager.send_personal_message(
                            websocket,
                            {"type": "error", "detail": "Failed to send message"}
                        )
            
            elif msg_type == "typing":
                await chat_manager.broadcast_to_room(
                    room_id,
                    {
                        "type": "typing",
                        "room_id": room_id,
                        "user_id": str(user_id),
                    },
                    exclude=websocket
                )
            
            elif msg_type == "read_receipt":
                await chat_manager.broadcast_to_room(
                    room_id,
                    {
                        "type": "read_receipt",
                        "room_id": room_id,
                        "reader_id": str(user_id),
                    },
                    exclude=websocket
                )
            
            else:
                await chat_manager.send_personal_message(
                    websocket,
                    {"type": "error", "detail": f"Unknown message type: {msg_type}"}
                )
    
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for user %s in room %s", user_id, room_id)
    except Exception as e:
        logger.error("WebSocket error for user %s in room %s: %s", user_id, room_id, e)
    finally:
        chat_manager.disconnect(websocket, room_id, str(user_id))
        
        # Notify room that user left
        await chat_manager.broadcast_to_room(
            room_id,
            {
                "type": "system",
                "event": "user_left",
                "room_id": room_id,
                "user_id": str(user_id),
            }
        )
