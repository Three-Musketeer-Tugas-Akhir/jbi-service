"""
PostgreSQL Advisory Lock utilities for distributed locking.

Uses PostgreSQL's native advisory lock mechanism to prevent
duplicate processing across multiple workers.
"""

import logging
import hashlib
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AdvisoryLock:
    """
    PostgreSQL Advisory Lock manager.
    
    Provides distributed locking using PostgreSQL's built-in
    advisory lock feature. Locks are session-scoped and 
    automatically released when the session disconnects.
    
    Usage:
        lock = AdvisoryLock(session, "asr:job-123")
        if await lock.acquire():
            try:
                # Process job...
                pass
            finally:
                await lock.release()
    """
    
    def __init__(self, session: AsyncSession, lock_name: str):
        """
        Initialize advisory lock.
        
        Args:
            session: SQLAlchemy async session
            lock_name: Unique lock identifier (e.g., "asr:job-uuid")
        """
        self.session = session
        self.lock_name = lock_name
        self.lock_id = self._name_to_id(lock_name)
        self.acquired = False
    
    @staticmethod
    def _name_to_id(name: str) -> int:
        """
        Convert lock name to numeric ID using hash.
        
        PostgreSQL advisory locks use 64-bit integers.
        We use MD5 hash and take the first 8 bytes as int64.
        """
        hash_bytes = hashlib.md5(name.encode()).digest()
        # Convert first 8 bytes to signed 64-bit integer
        return int.from_bytes(hash_bytes[:8], byteorder='big', signed=True)
    
    async def acquire(self, wait: bool = False) -> bool:
        """
        Acquire advisory lock.
        
        Args:
            wait: If True, block until lock is available.
                  If False, return immediately (non-blocking).
        
        Returns:
            True if lock acquired, False otherwise.
        """
        try:
            if wait:
                # Blocking - waits until lock is available
                result = await self.session.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": self.lock_id}
                )
                self.acquired = True
                logger.debug(f"Advisory lock acquired (blocking): {self.lock_name}")
                return True
            else:
                # Non-blocking - returns immediately
                result = await self.session.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id) as acquired"),
                    {"lock_id": self.lock_id}
                )
                row = result.fetchone()
                self.acquired = row.acquired if row else False
                
                if self.acquired:
                    logger.debug(f"Advisory lock acquired: {self.lock_name}")
                else:
                    logger.debug(f"Advisory lock busy: {self.lock_name}")
                
                return self.acquired
                
        except Exception as e:
            logger.error(f"Failed to acquire advisory lock {self.lock_name}: {e}")
            return False
    
    async def release(self) -> bool:
        """
        Release advisory lock.
        
        Returns:
            True if lock was released, False if not owned.
        """
        if not self.acquired:
            return False
        
        try:
            result = await self.session.execute(
                text("SELECT pg_advisory_unlock(:lock_id) as released"),
                {"lock_id": self.lock_id}
            )
            row = result.fetchone()
            released = row.released if row else False
            
            if released:
                self.acquired = False
                logger.debug(f"Advisory lock released: {self.lock_name}")
            else:
                logger.warning(
                    f"Advisory lock release failed (not owned?): {self.lock_name}"
                )
            
            return released
            
        except Exception as e:
            logger.error(f"Failed to release advisory lock {self.lock_name}: {e}")
            return False
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.acquire(wait=False)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - always release lock."""
        if self.acquired:
            await self.release()


class DistributedLockManager:
    """
    Helper class for managing distributed locks in pipeline workers.
    
    Provides convenient methods for locking jobs by stage.
    """
    
    @staticmethod
    def get_lock_name(stage: str, job_id: str) -> str:
        """
        Generate a unique lock name for a job stage.
        
        Args:
            stage: Pipeline stage (e.g., 'asr', 'cropping', 'detection')
            job_id: Job UUID
        
        Returns:
            Lock name string
        """
        return f"pipeline:{stage}:{job_id}"
    
    @staticmethod
    async def try_lock_job(
        session: AsyncSession,
        stage: str,
        job_id: str
    ) -> Optional[AdvisoryLock]:
        """
        Try to acquire a lock for a job.
        
        Args:
            session: Database session
            stage: Pipeline stage
            job_id: Job ID
        
        Returns:
            AdvisoryLock if acquired, None if busy
        """
        lock_name = DistributedLockManager.get_lock_name(stage, job_id)
        lock = AdvisoryLock(session, lock_name)
        
        if await lock.acquire(wait=False):
            return lock
        
        return None
