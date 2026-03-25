"""Tests for RefreshTokenRepository."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.db.models.auth import RefreshToken, User


@pytest.mark.asyncio
class TestRefreshTokenRepository:
    """Tests for RefreshTokenRepository."""
    
    async def test_create_token(self, db_session):
        """Test creating a refresh token record."""
        # Create a test user first
        user = User(
            id=uuid4(),
            email="test@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        jti = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        token = await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=expires_at
        )
        
        assert token.jti == jti
        assert token.user_id == user.id
        assert token.is_active is True
        assert token.is_revoked is False
        assert token.is_expired is False
    
    async def test_get_by_jti(self, db_session):
        """Test finding token by JTI."""
        user = User(
            id=uuid4(),
            email="test2@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        jti = uuid4()
        
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        
        found = await repo.get_by_jti(jti)
        
        assert found is not None
        assert found.jti == jti
        assert found.user_id == user.id
    
    async def test_get_by_jti_not_found(self, db_session):
        """Test finding non-existent token returns None."""
        repo = RefreshTokenRepository(db_session)
        
        found = await repo.get_by_jti(uuid4())
        
        assert found is None
    
    async def test_revoke_token(self, db_session):
        """Test revoking a token."""
        user = User(
            id=uuid4(),
            email="test3@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        jti = uuid4()
        
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        
        result = await repo.revoke(jti)
        assert result is True
        
        # Verify it's revoked
        token = await repo.get_by_jti(jti)
        assert token.is_revoked is True
        assert token.is_active is False
        assert token.revoked_at is not None
    
    async def test_revoke_nonexistent_token(self, db_session):
        """Test revoking a non-existent token returns False."""
        repo = RefreshTokenRepository(db_session)
        
        result = await repo.revoke(uuid4())
        assert result is False
    
    async def test_is_valid(self, db_session):
        """Test token validity check."""
        user = User(
            id=uuid4(),
            email="test4@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        jti = uuid4()
        
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        
        # Valid token
        assert await repo.is_valid(jti) is True
        
        # After revoke
        await repo.revoke(jti)
        assert await repo.is_valid(jti) is False
    
    async def test_is_valid_expired_token(self, db_session):
        """Test that expired token is not valid."""
        user = User(
            id=uuid4(),
            email="test5@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        jti = uuid4()
        
        # Create expired token
        await repo.create(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        
        assert await repo.is_valid(jti) is False
    
    async def test_get_active_tokens_for_user(self, db_session):
        """Test getting active tokens for user."""
        user = User(
            id=uuid4(),
            email="test6@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        # Create multiple tokens
        for i in range(3):
            await repo.create(
                jti=uuid4(),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        tokens = await repo.get_active_tokens_for_user(user.id)
        
        assert len(tokens) == 3
        for token in tokens:
            assert token.is_active is True
            assert token.user_id == user.id
    
    async def test_get_active_tokens_for_user_excludes_revoked(self, db_session):
        """Test that revoked tokens are not returned as active."""
        user = User(
            id=uuid4(),
            email="test7@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        # Create active and revoked tokens
        jti1 = uuid4()
        jti2 = uuid4()
        
        await repo.create(
            jti=jti1,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await repo.create(
            jti=jti2,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await repo.revoke(jti2)
        
        tokens = await repo.get_active_tokens_for_user(user.id)
        
        assert len(tokens) == 1
        assert tokens[0].jti == jti1
    
    async def test_revoke_all_for_user(self, db_session):
        """Test revoking all tokens for user."""
        user = User(
            id=uuid4(),
            email="test8@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        # Create multiple tokens
        for _ in range(3):
            await repo.create(
                jti=uuid4(),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        count = await repo.revoke_all_for_user(user.id)
        assert count == 3
        
        # Verify all are revoked
        tokens = await repo.get_active_tokens_for_user(user.id)
        assert len(tokens) == 0
    
    async def test_revoke_all_for_user_only_affects_target_user(self, db_session):
        """Test that revoke_all only affects specified user."""
        user1 = User(
            id=uuid4(),
            email="user1@example.com",
            password_hash="hashed_password"
        )
        user2 = User(
            id=uuid4(),
            email="user2@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user1)
        db_session.add(user2)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        # Create tokens for both users
        for _ in range(2):
            await repo.create(
                jti=uuid4(),
                user_id=user1.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        for _ in range(3):
            await repo.create(
                jti=uuid4(),
                user_id=user2.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        count = await repo.revoke_all_for_user(user1.id)
        assert count == 2
        
        # Verify user2's tokens are still active
        user2_tokens = await repo.get_active_tokens_for_user(user2.id)
        assert len(user2_tokens) == 3
    
    async def test_cleanup_expired(self, db_session):
        """Test cleaning up expired tokens."""
        user = User(
            id=uuid4(),
            email="test9@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        # Create expired tokens
        for _ in range(5):
            await repo.create(
                jti=uuid4(),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1)
            )
        
        # Create valid tokens
        for _ in range(3):
            await repo.create(
                jti=uuid4(),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        deleted = await repo.cleanup_expired(batch_size=100)
        
        assert deleted == 5
        
        # Verify only valid tokens remain
        active_tokens = await repo.get_active_tokens_for_user(user.id)
        assert len(active_tokens) == 3
    
    async def test_create_with_rotation(self, db_session):
        """Test creating a token with rotation link."""
        user = User(
            id=uuid4(),
            email="test10@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user)
        await db_session.flush()
        
        repo = RefreshTokenRepository(db_session)
        
        # Create original token
        original_jti = uuid4()
        await repo.create(
            jti=original_jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        
        # Create rotated token
        new_jti = uuid4()
        await repo.create(
            jti=new_jti,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            rotated_from_jti=original_jti
        )
        
        # Verify rotation link
        original = await repo.get_by_jti(original_jti)
        assert original.rotated_to_jti == new_jti
