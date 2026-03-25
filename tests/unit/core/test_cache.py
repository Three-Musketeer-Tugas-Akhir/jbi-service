"""Unit tests for caching infrastructure."""

import time
import pytest
from app.core.cache import InMemoryCache, job_status_cache


class TestInMemoryCache:
    """Test suite for InMemoryCache class."""
    
    def test_cache_stores_and_retrieves_value(self):
        """AC: Cache stores and retrieves values."""
        cache = InMemoryCache()
        
        cache.set("key1", "value1")
        result = cache.get("key1")
        
        assert result == "value1"
    
    def test_cache_returns_none_for_missing_key(self):
        """AC: Missing keys return None."""
        cache = InMemoryCache()
        
        result = cache.get("nonexistent")
        
        assert result is None
    
    def test_cache_expires_after_ttl(self):
        """AC: Expired entries return None."""
        cache = InMemoryCache(default_ttl=0.1)  # 100ms TTL for testing
        
        cache.set("key1", "value1")
        
        # Should exist immediately
        assert cache.get("key1") == "value1"
        
        # Wait for expiration
        time.sleep(0.15)
        
        # Should be expired
        assert cache.get("key1") is None
    
    def test_cache_default_ttl_is_2_seconds(self):
        """AC: TTL defaults to 2 seconds per NFR3."""
        cache = InMemoryCache()
        
        assert cache._default_ttl == 2.0
    
    def test_cache_allows_custom_ttl(self):
        """AC: Custom TTL overrides default."""
        cache = InMemoryCache(default_ttl=10.0)
        
        cache.set("key1", "value1", ttl=0.1)
        
        # Should exist immediately
        assert cache.get("key1") == "value1"
        
        # Wait for custom TTL expiration
        time.sleep(0.15)
        
        # Should be expired
        assert cache.get("key1") is None
    
    def test_cache_delete_removes_entry(self):
        """AC: Delete removes entry and returns True."""
        cache = InMemoryCache()
        
        cache.set("key1", "value1")
        deleted = cache.delete("key1")
        
        assert deleted is True
        assert cache.get("key1") is None
    
    def test_cache_delete_returns_false_for_missing(self):
        """AC: Delete returns False for non-existent key."""
        cache = InMemoryCache()
        
        deleted = cache.delete("nonexistent")
        
        assert deleted is False
    
    def test_cache_clear_removes_all(self):
        """AC: Clear removes all entries."""
        cache = InMemoryCache()
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.size() == 0
    
    def test_cache_size_returns_count(self):
        """AC: Size returns correct count."""
        cache = InMemoryCache()
        
        assert cache.size() == 0
        
        cache.set("key1", "value1")
        assert cache.size() == 1
        
        cache.set("key2", "value2")
        assert cache.size() == 2
    
    def test_cache_cleanup_expired_removes_old_entries(self):
        """AC: Cleanup removes expired entries."""
        cache = InMemoryCache()
        
        # Set one with short TTL, one with long
        cache.set("short", "value1", ttl=0.1)
        cache.set("long", "value2", ttl=10.0)
        
        time.sleep(0.15)
        
        removed = cache.cleanup_expired()
        
        assert removed == 1
        assert cache.get("short") is None
        assert cache.get("long") == "value2"
    
    def test_cache_can_store_complex_objects(self):
        """AC: Cache can store dictionaries and lists."""
        cache = InMemoryCache()
        
        complex_data = {
            "id": "123",
            "status": "PROCESSING",
            "progress": 45,
            "segments": [1, 2, 3]
        }
        
        cache.set("job:123", complex_data)
        result = cache.get("job:123")
        
        assert result == complex_data
    
    def test_job_status_cache_singleton_exists(self):
        """AC: job_status_cache singleton is available."""
        assert job_status_cache is not None
        assert isinstance(job_status_cache, InMemoryCache)


class TestCacheConcurrency:
    """Test thread safety of cache operations."""
    
    def test_concurrent_reads_and_writes(self):
        """AC: Cache is thread-safe for concurrent access."""
        import threading
        
        cache = InMemoryCache()
        errors = []
        
        def writer():
            try:
                for i in range(100):
                    cache.set(f"key_{i}", f"value_{i}")
            except Exception as e:
                errors.append(f"Writer error: {e}")
        
        def reader():
            try:
                for i in range(100):
                    cache.get(f"key_{i}")
            except Exception as e:
                errors.append(f"Reader error: {e}")
        
        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Concurrent access errors: {errors}"
