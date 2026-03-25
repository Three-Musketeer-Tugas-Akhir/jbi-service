"""Tests for TokenRefreshService."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.services.token_refresh_service import TokenRefreshService
from app.services.auth_service import JWTAuthService
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.db.models.auth import User


@pytest.fixture
def auth_service():
    """Create JWTAuthService instance for testing."""
    service = JWTAuthService()
    service.secret_key = "test-secret-key-that-is-32-chars-long-for-security"
    return service


@pytest.mark.asyncio
class TestTokenRefreshService:
    """Tests for TokenRefreshService."""
    
    async def test_store_refresh_token(self, db_session, auth_service):
        """Test storing a refresh token in database."""
        user = User(
            id=uuid4(),
            email="test@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create refresh token
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        service = TokenRefreshService(db_session)
        result = await service.store_refresh_token(refresh_token, user.id)
        
        assert result["success"] is True
        
        # Verify stored in database
        repo = RefreshTokenRepository(db_session)
        assert await repo.is_valid(jti) is True
    
    async def test_store_refresh_token_invalid_token(self, db_session):
        """Test storing an invalid token fails gracefully."""
        user = User(
            id=uuid4(),
            email="test2@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        service = TokenRefreshService(db_session)
        result = await service.store_refresh_token("invalid.token.here", user.id)
        
        assert result["success"] is False
    
    async def test_rotate_refresh_token_success(self, db_session, auth_service):
        """Test successful token refresh with rotation."""
        user = User(
            id=uuid4(),
            email="test3@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create and store initial refresh token
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await db_session.commit()
        
        # Refresh
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(refresh_token)
        
        assert result["success"] is True
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["message"] == "Token refreshed successfully"
        
        # Old token should be revoked
        assert await repo.is_valid(jti) is False
    
    async def test_rotate_with_revoked_token(self, db_session, auth_service):
        """Test refresh with revoked token fails."""
        user = User(
            id=uuid4(),
            email="test4@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await repo.revoke(jti)
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(refresh_token)
        
        assert result["success"] is False
        assert "Invalid refresh token" in result["message"]
    
    async def test_rotate_with_expired_token(self, db_session, auth_service):
        """Test refresh with expired token fails."""
        user = User(
            id=uuid4(),
            email="test5@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        # Store with already expired timestamp
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(refresh_token)
        
        assert result["success"] is False
        assert "expired" in result["message"].lower()
    
    async def test_rotate_with_invalid_token_type(self, db_session, auth_service):
        """Test refresh with access token (wrong type) fails."""
        user = User(
            id=uuid4(),
            email="test6@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create access token instead of refresh token
        access_token = auth_service.create_access_token(user.id, "annotator")
        
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(access_token)
        
        assert result["success"] is False
        assert "Invalid token type" in result["message"]
    
    async def test_rotate_with_missing_jti(self, db_session, auth_service):
        """Test refresh with token missing jti claim fails."""
        import jwt
        
        user = User(
            id=uuid4(),
            email="test7@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create token without jti
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.id),
            "role": "annotator",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
            "type": "refresh",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int(now.timestamp()),
        }
        token_without_jti = jwt.encode(
            payload,
            auth_service.secret_key,
            algorithm=auth_service.algorithm
        )
        
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(token_without_jti)
        
        assert result["success"] is False
        assert "missing jti claim" in result["message"]
    
    async def test_rotate_with_nonexistent_token(self, db_session, auth_service):
        """Test refresh with token not in database fails."""
        user = User(
            id=uuid4(),
            email="test8@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create token but don't store it
        refresh_token, _ = auth_service.create_refresh_token(user.id, "annotator")
        
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(refresh_token)
        
        assert result["success"] is False
        assert "Invalid refresh token" in result["message"]
    
    async def test_revoke_refresh_token(self, db_session, auth_service):
        """Test revoking a refresh token."""
        user = User(
            id=uuid4(),
            email="test9@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        result = await service.revoke_refresh_token(refresh_token)
        
        assert result["success"] is True
        assert await repo.is_valid(jti) is False
    
    async def test_revoke_refresh_token_invalid(self, db_session):
        """Test revoking an invalid token."""
        service = TokenRefreshService(db_session)
        result = await service.revoke_refresh_token("invalid.token.here")
        
        assert result["success"] is False
    
    async def test_revoke_refresh_token_already_revoked(self, db_session, auth_service):
        """Test revoking an already revoked token returns appropriate response."""
        user = User(
            id=uuid4(),
            email="test10@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await repo.revoke(jti)
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        result = await service.revoke_refresh_token(refresh_token)
        
        # Should return success=False but not error
        assert result["success"] is False
    
    async def test_revoke_all_user_tokens(self, db_session, auth_service):
        """Test revoking all tokens for a user."""
        user = User(
            id=uuid4(),
            email="test11@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create multiple tokens
        repo = RefreshTokenRepository(db_session)
        for _ in range(3):
            _, jti = auth_service.create_refresh_token(user.id, "annotator")
            await repo.create(
                jti=jti,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        count = await service.revoke_all_user_tokens(user.id)
        
        assert count == 3
        
        # Verify all are revoked
        active_tokens = await repo.get_active_tokens_for_user(user.id)
        assert len(active_tokens) == 0
    
    async def test_token_rotation_creates_valid_new_tokens(self, db_session, auth_service):
        """Test that rotated tokens are valid and can be used."""
        user = User(
            id=uuid4(),
            email="test12@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create and store initial token
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await db_session.commit()
        
        # Rotate
        service = TokenRefreshService(db_session)
        result = await service.rotate_refresh_token(refresh_token)
        
        assert result["success"] is True
        
        # Verify new access token is valid
        new_access_token = result["access_token"]
        access_payload = auth_service.verify_token(new_access_token, expected_type="access")
        assert access_payload["sub"] == str(user.id)
        assert access_payload["role"] == "annotator"
        
        # Verify new refresh token is valid
        new_refresh_token = result["refresh_token"]
        refresh_payload = auth_service.verify_token(new_refresh_token, expected_type="refresh")
        assert refresh_payload["sub"] == str(user.id)
        assert refresh_payload["role"] == "annotator"
        assert "jti" in refresh_payload
    
    async def test_old_token_cannot_be_reused_after_rotation(self, db_session, auth_service):
        """Test that old refresh token cannot be used after rotation."""
        user = User(
            id=uuid4(),
            email="test13@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        # Create and store initial token
        refresh_token, jti = auth_service.create_refresh_token(user.id, "annotator")
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await db_session.commit()
        
        # Rotate
        service = TokenRefreshService(db_session)
        await service.rotate_refresh_token(refresh_token)
        
        # Try to use old token again
        result = await service.rotate_refresh_token(refresh_token)
        
        assert result["success"] is False
        assert "Invalid refresh token" in result["message"]
