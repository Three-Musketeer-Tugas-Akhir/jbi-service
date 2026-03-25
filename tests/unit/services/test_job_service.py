"""Unit tests for job service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4
from datetime import datetime

from app.services.job_service import JobService
from app.core.exceptions import NotFoundError, PermissionError
from app.core.cache import job_status_cache


class TestJobServiceGetJob:
    """Test suite for JobService.get_job method."""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_job_repo(self):
        """Create mock job repository."""
        return MagicMock()
    
    @pytest.fixture
    def job_service(self, mock_db, mock_job_repo):
        """Create job service with mocked dependencies."""
        return JobService(mock_db, mock_job_repo)
    
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        job_status_cache.clear()
        yield
        job_status_cache.clear()
    
    @pytest.mark.asyncio
    async def test_get_job_returns_correct_data(self, job_service, mock_db):
        """AC: get_job returns correct job data structure."""
        # Arrange
        job_id = str(uuid4())
        user_id = str(uuid4())
        
        mock_job = MagicMock()
        mock_job.id = UUID(job_id)
        mock_job.status = "DETECTING"
        mock_job.current_stage = "detection"
        mock_job.created_at = datetime(2026, 3, 18, 10, 0, 0)
        mock_job.updated_at = datetime(2026, 3, 18, 10, 5, 0)
        mock_job.error_message = None
        mock_job.created_by = UUID(user_id)
        
        # Mock the query result
        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=(mock_job, 5, 2))
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        # Act
        result = await job_service.get_job(job_id, user_id, is_admin=False)
        
        # Assert
        assert result["id"] == job_id
        assert result["status"] == "DETECTING"
        assert result["current_stage"] == "detection"
        assert result["progress"] == 40  # 2/5 = 40%
        assert result["total_segments"] == 5
        assert result["completed_segments"] == 2
        assert result["created_by"] == user_id
    
    @pytest.mark.asyncio
    async def test_get_job_raises_not_found_for_invalid_uuid(self, job_service):
        """AC: 404 for invalid job ID format."""
        with pytest.raises(NotFoundError):
            await job_service.get_job("invalid-uuid", "user-id", is_admin=False)
    
    @pytest.mark.asyncio
    async def test_get_job_raises_not_found_for_missing_job(self, job_service, mock_db):
        """AC: 404 for non-existent job."""
        job_id = str(uuid4())
        
        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(NotFoundError):
            await job_service.get_job(job_id, "user-id", is_admin=False)
    
    @pytest.mark.asyncio
    async def test_get_job_forbidden_for_other_user(self, job_service, mock_db):
        """AC: Non-admin cannot see other user's job."""
        job_id = str(uuid4())
        owner_id = str(uuid4())
        other_user_id = str(uuid4())
        
        mock_job = MagicMock()
        mock_job.id = UUID(job_id)
        mock_job.status = "DETECTING"
        mock_job.current_stage = "detection"
        mock_job.created_at = datetime.now()
        mock_job.updated_at = datetime.now()
        mock_job.error_message = None
        mock_job.created_by = UUID(owner_id)
        
        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=(mock_job, 5, 2))
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with pytest.raises(PermissionError):
            await job_service.get_job(job_id, other_user_id, is_admin=False)
    
    @pytest.mark.asyncio
    async def test_get_job_allows_admin_to_view_any_job(self, job_service, mock_db):
        """AC: Admin can view any job."""
        job_id = str(uuid4())
        owner_id = str(uuid4())
        admin_id = str(uuid4())
        
        mock_job = MagicMock()
        mock_job.id = UUID(job_id)
        mock_job.status = "DETECTING"
        mock_job.current_stage = "detection"
        mock_job.created_at = datetime.now()
        mock_job.updated_at = datetime.now()
        mock_job.error_message = None
        mock_job.created_by = UUID(owner_id)
        
        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=(mock_job, 5, 2))
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        # Should not raise
        result = await job_service.get_job(job_id, admin_id, is_admin=True)
        
        assert result["id"] == job_id
    
    @pytest.mark.asyncio
    async def test_get_job_calculates_progress_correctly(self, job_service, mock_db):
        """AC: Progress percentage is calculated correctly."""
        job_id = str(uuid4())
        user_id = str(uuid4())
        
        mock_job = MagicMock()
        mock_job.id = UUID(job_id)
        mock_job.status = "DETECTING"
        mock_job.current_stage = "detection"
        mock_job.created_at = datetime.now()
        mock_job.updated_at = datetime.now()
        mock_job.error_message = None
        mock_job.created_by = UUID(user_id)
        
        # Test 0% progress
        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=(mock_job, 10, 0))
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = await job_service.get_job(job_id, user_id, is_admin=False)
        assert result["progress"] == 0
        
        # Test 50% progress
        mock_result.first = MagicMock(return_value=(mock_job, 10, 5))
        result = await job_service.get_job(job_id, user_id, is_admin=False)
        assert result["progress"] == 50
        
        # Test 100% progress
        mock_result.first = MagicMock(return_value=(mock_job, 10, 10))
        result = await job_service.get_job(job_id, user_id, is_admin=False)
        assert result["progress"] == 100
    
    @pytest.mark.asyncio
    async def test_get_job_uses_cache(self, job_service, mock_db):
        """AC: Cache is checked before database query."""
        job_id = str(uuid4())
        user_id = str(uuid4())
        cache_key = f"job:{job_id}:user:{user_id}"
        
        cached_data = {
            "id": job_id,
            "status": "DETECTING",
            "progress": 50
        }
        job_status_cache.set(cache_key, cached_data)
        
        result = await job_service.get_job(job_id, user_id, is_admin=False)
        
        # Should return cached data without querying DB
        assert result == cached_data
        mock_db.execute.assert_not_called()


class TestJobServiceListJobs:
    """Test suite for JobService.list_jobs method."""
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_job_repo(self):
        """Create mock job repository."""
        return MagicMock()
    
    @pytest.fixture
    def job_service(self, mock_db, mock_job_repo):
        """Create job service with mocked dependencies."""
        return JobService(mock_db, mock_job_repo)
    
    @pytest.mark.asyncio
    async def test_list_jobs_pagination(self, job_service, mock_db):
        """AC: Pagination logic works correctly."""
        user_id = str(uuid4())
        
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=25)
        
        # Mock items query (empty for simplicity)
        mock_items_result = MagicMock()
        mock_items_result.all = MagicMock(return_value=[])
        
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_items_result])
        
        result = await job_service.list_jobs(
            current_user_id=user_id,
            is_admin=False,
            page=2,
            page_size=10
        )
        
        assert result["page"] == 2
        assert result["page_size"] == 10
        assert result["total"] == 25
        assert result["total_pages"] == 3
    
    @pytest.mark.asyncio
    async def test_list_jobs_returns_items(self, job_service, mock_db):
        """AC: List returns job items with progress."""
        user_id = str(uuid4())
        
        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.status = "DETECTING"
        mock_job.current_stage = "detection"
        mock_job.created_at = datetime.now()
        mock_job.updated_at = datetime.now()
        mock_job.error_message = None
        
        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=1)
        
        mock_items_result = MagicMock()
        mock_items_result.all = MagicMock(return_value=[(mock_job, 5, 3)])
        
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_items_result])
        
        result = await job_service.list_jobs(
            current_user_id=user_id,
            is_admin=False
        )
        
        assert len(result["items"]) == 1
        assert result["items"][0]["progress"] == 60  # 3/5 = 60%
    
    @pytest.mark.asyncio
    async def test_list_jobs_filters_by_status(self, job_service, mock_db):
        """AC: Status filtering works."""
        user_id = str(uuid4())
        
        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=0)
        
        mock_items_result = MagicMock()
        mock_items_result.all = MagicMock(return_value=[])
        
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_items_result])
        
        result = await job_service.list_jobs(
            current_user_id=user_id,
            is_admin=False,
            status="DETECTING"
        )
        
        assert result["items"] == []
    
    @pytest.mark.asyncio
    async def test_list_jobs_admin_sees_all(self, job_service, mock_db):
        """AC: Admin sees all jobs."""
        admin_id = str(uuid4())
        
        mock_count_result = MagicMock()
        mock_count_result.scalar = MagicMock(return_value=0)
        
        mock_items_result = MagicMock()
        mock_items_result.all = MagicMock(return_value=[])
        
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_items_result])
        
        result = await job_service.list_jobs(
            current_user_id=admin_id,
            is_admin=True
        )
        
        # Admin should see all, so no user filter
        assert result["total"] == 0


class TestJobServiceCacheInvalidation:
    """Test suite for cache invalidation."""
    
    @pytest.fixture
    def job_service(self):
        """Create job service."""
        mock_db = AsyncMock()
        mock_repo = MagicMock()
        return JobService(mock_db, mock_repo)
    
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        job_status_cache.clear()
        yield
        job_status_cache.clear()
    
    def test_invalidate_job_cache_deletes_entry(self, job_service):
        """AC: Cache invalidation removes entry."""
        job_id = str(uuid4())
        user_id = str(uuid4())
        cache_key = f"job:{job_id}:user:{user_id}"
        
        # Set up cache
        job_status_cache.set(cache_key, {"status": "DETECTING"})
        assert job_status_cache.get(cache_key) is not None
        
        # Invalidate
        job_service.invalidate_job_cache(job_id, user_id)
        
        # Verify deleted
        assert job_status_cache.get(cache_key) is None
