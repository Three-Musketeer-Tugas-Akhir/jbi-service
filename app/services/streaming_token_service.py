"""
Streaming Token Service.

Generates and verifies JWT tokens for video streaming access.
Tokens are short-lived and grant temporary access to specific video assets.
"""

import jwt
from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Optional

from app.core.config import settings


class StreamingTokenService:
    """Service for generating and verifying streaming tokens."""

    @staticmethod
    def generate_token(user_id: UUID, object_path: str) -> str:
        """
        Generate JWT token for video streaming.

        Args:
            user_id: User ID requesting access
            object_path: MinIO object path (e.g., jobs/{uuid}/segments/segment_0000.mp4)

        Returns:
            JWT token string
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=settings.streaming_token_expire_days)
        
        payload = {
            "sub": str(user_id),
            "obj": object_path,
            "exp": expires,
            "iat": now,
            "type": "streaming"
        }
        
        return jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm
        )

    @staticmethod
    def verify_token(token: str, object_path: str) -> Optional[UUID]:
        """
        Verify streaming token and return user_id if valid.

        Args:
            token: JWT token from query parameter
            object_path: Expected object path

        Returns:
            User UUID if token is valid, None otherwise
        """
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )

            # Check token type
            if payload.get("type") != "streaming":
                return None

            # Check object path matches (prevent token reuse for different objects)
            if payload.get("obj") != object_path:
                return None

            return UUID(payload.get("sub"))
            
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            return None


# Global instance
streaming_token_service = StreamingTokenService()
