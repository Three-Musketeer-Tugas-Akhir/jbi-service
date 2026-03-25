"""Caching infrastructure for the application.

Provides TTL-based caching for frequently accessed data like job status.
Designed to be simple for MVP, with upgrade path to Redis for scale.
"""

import time
from typing import Optional, Any, Dict, Tuple
from threading import Lock


class InMemoryCache:
    """Simple thread-safe TTL cache.
    
    Default TTL is 2 seconds for job status responses per NFR3.
    
    Attributes:
        _cache: Dictionary storing (value, expiry_time) tuples
        _lock: Thread lock for concurrent access safety
        _default_ttl: Default time-to-live in seconds
    """
    
    def __init__(self, default_ttl: float = 2.0):
        """Initialize cache with default TTL.
        
        Args:
            default_ttl: Default time-to-live in seconds
        """
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = Lock()
        self._default_ttl = default_ttl
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            value, expiry = self._cache[key]
            
            # Check if expired
            if time.time() > expiry:
                del self._cache[key]
                return None
            
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache with TTL.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        ttl = ttl or self._default_ttl
        expiry = time.time() + ttl
        
        with self._lock:
            self._cache[key] = (value, expiry)
    
    def delete(self, key: str) -> bool:
        """Delete value from cache.
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if key existed and was deleted, False otherwise
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cached values."""
        with self._lock:
            self._cache.clear()
    
    def keys(self) -> list:
        """Get all cache keys (for testing/debugging).
        
        Returns:
            List of all cache keys
        """
        with self._lock:
            return list(self._cache.keys())
    
    def size(self) -> int:
        """Get number of cached items.
        
        Returns:
            Number of items in cache
        """
        with self._lock:
            return len(self._cache)
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries.
        
        Returns:
            Number of expired entries removed
        """
        current_time = time.time()
        expired_count = 0
        
        with self._lock:
            expired_keys = [
                key for key, (_, expiry) in self._cache.items()
                if current_time > expiry
            ]
            for key in expired_keys:
                del self._cache[key]
                expired_count += 1
        
        return expired_count


# Singleton instances for different cache purposes
job_status_cache = InMemoryCache(default_ttl=2.0)  # 2-second TTL per NFR3


def invalidate_job_cache(job_id: str, user_id: Optional[str] = None) -> None:
    """Invalidate cache entries for a job.
    
    Called by workers when job status changes to ensure
    fresh data on next poll.
    
    Args:
        job_id: Job UUID string
        user_id: Optional specific user cache to invalidate
    """
    if user_id:
        # Invalidate specific user-job combination
        cache_key = f"job:{job_id}:user:{user_id}"
        job_status_cache.delete(cache_key)
    else:
        # TODO: For MVP, we don't track all users who might have
        # cached this job. In production, consider:
        # 1. Using a cache key pattern that includes job_id prefix
        # 2. Redis with SCAN to find matching keys
        # 3. Shorter TTL for shared resources
        # For now, rely on TTL expiration
        pass
