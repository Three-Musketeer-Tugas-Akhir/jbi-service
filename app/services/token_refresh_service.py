"""
Token Refresh Service.

Handles refresh token rotation and validation with database tracking.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.services.auth_service import jwt_auth_service
from app.repositories.refresh_token_repository import RefreshTokenRepository


class TokenRefreshService:
    """Service for token refresh operations with rotation."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.token_repo = RefreshTokenRepository(session)
    
    async def store_refresh_token(
        self, 
        refresh_token: str,
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Store refresh token in database for rotation tracking.
        
        Args:
            refresh_token: The refresh token string
            user_id: User ID associated with the token
            
        Returns:
            Dict with success status
        """
        try:
            # Decode to get jti and expiry
            payload = jwt_auth_service.decode_token(refresh_token)
            
            jti_str = payload.get("jti")
            if not jti_str:
                return {"success": False, "message": "Token missing jti claim"}
            
            jti = UUID(jti_str)
            exp_timestamp = payload.get("exp")
            
            if not exp_timestamp:
                return {"success": False, "message": "Token missing exp claim"}
            
            expires_at = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            
            # Store in database
            await self.token_repo.create(
                jti=jti,
                user_id=user_id,
                expires_at=expires_at
            )
            
            return {"success": True}
            
        except (InvalidTokenError, ValueError) as e:
            return {"success": False, "message": str(e)}
    
    async def rotate_refresh_token(
        self, 
        refresh_token: str
    ) -> Dict[str, Any]:
        """
        Refresh access token using refresh token with rotation.
        
        Args:
            refresh_token: Current refresh token
            
        Returns:
            Dict with success status, tokens, and message
        """
        try:
            # Step 1: Decode token to get jti (without verifying expiration)
            try:
                payload = jwt_auth_service.decode_token(refresh_token)
            except InvalidTokenError:
                return {"success": False, "message": "Invalid refresh token"}
            
            # Step 2: Verify it's a refresh token
            if payload.get("type") != "refresh":
                return {"success": False, "message": "Invalid token type"}
            
            # Step 3: Get jti from payload
            jti_str = payload.get("jti")
            if not jti_str:
                return {"success": False, "message": "Token missing jti claim"}
            
            try:
                jti = UUID(jti_str)
            except ValueError:
                return {"success": False, "message": "Invalid jti in token"}
            
            # Step 4: Check if token exists in database and is valid
            token_record = await self.token_repo.get_by_jti(jti)
            
            if token_record is None:
                return {"success": False, "message": "Invalid refresh token"}
            
            if token_record.is_revoked:
                return {"success": False, "message": "Invalid refresh token"}
            
            if token_record.is_expired:
                return {"success": False, "message": "Refresh token expired, please login again"}
            
            # Step 5: Verify full token (signature, expiration)
            try:
                jwt_auth_service.verify_token(refresh_token, expected_type="refresh")
            except ExpiredSignatureError:
                # Mark as expired in database for cleanup
                await self.token_repo.revoke(jti)
                return {"success": False, "message": "Refresh token expired, please login again"}
            
            # Step 6: Get user info
            user_id = token_record.user_id
            role = payload.get("role")
            
            if not role:
                return {"success": False, "message": "Token missing role claim"}
            
            # Step 7: Generate new token pair
            new_access_token = jwt_auth_service.create_access_token(user_id, role)
            new_refresh_token, new_jti = jwt_auth_service.create_refresh_token(
                user_id, role
            )
            
            # Step 8: Store new refresh token with rotation link
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=jwt_auth_service.refresh_token_expire_days
            )
            await self.token_repo.create(
                jti=new_jti,
                user_id=user_id,
                expires_at=expires_at,
                rotated_from_jti=jti
            )
            
            # Step 9: Revoke old refresh token
            await self.token_repo.revoke(jti)
            
            # Step 10: Commit transaction
            await self.session.commit()
            
            return {
                "success": True,
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "message": "Token refreshed successfully"
            }
            
        except Exception as e:
            await self.session.rollback()
            return {"success": False, "message": str(e)}
    
    async def revoke_refresh_token(
        self, 
        refresh_token: str
    ) -> Dict[str, Any]:
        """
        Revoke a refresh token.
        
        Args:
            refresh_token: Refresh token to revoke
            
        Returns:
            Dict with success status
        """
        try:
            payload = jwt_auth_service.decode_token(refresh_token)
            jti_str = payload.get("jti")
            
            if not jti_str:
                return {"success": False, "message": "Token missing jti claim"}
            
            jti = UUID(jti_str)
            revoked = await self.token_repo.revoke(jti)
            
            if revoked:
                await self.session.commit()
                return {"success": True}
            else:
                return {"success": False, "message": "Token not found or already revoked"}
            
        except (InvalidTokenError, ValueError) as e:
            return {"success": False, "message": str(e)}
        except Exception as e:
            await self.session.rollback()
            return {"success": False, "message": str(e)}
    
    async def revoke_all_user_tokens(self, user_id: UUID) -> int:
        """
        Revoke all refresh tokens for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Number of tokens revoked
        """
        count = await self.token_repo.revoke_all_for_user(user_id)
        await self.session.commit()
        return count
