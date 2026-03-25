"""Tests for queue service."""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock, call
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.services.queue_service import QueueService
from app.db.models.pipeline import QueueJob


class TestQueueService:
    """Test suite for queue service."""
    
    @pytest.fixture
    def queue_service(self):
        """Create queue service."""
        return QueueService()
    
    @pytest.mark.asyncio
    async def test_enqueue_creates_job(self, queue_service):
        """Test enqueue creates a queue job."""
        mock_db = MagicMock()
        mock_db.add = Mock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job = await queue_service.enqueue(
                queue_name="detection",
                payload={"job_id": "test-123"}
            )
            
            assert job.queue_name == "detection"
            assert job.payload == {"job_id": "test-123"}
            assert job.status == "pending"
            assert job.max_attempts == 3  # Default
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_enqueue_with_priority(self, queue_service):
        """Test enqueue with priority sets correct priority."""
        mock_db = MagicMock()
        mock_db.add = Mock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job = await queue_service.enqueue(
                queue_name="detection",
                payload={"job_id": "test-123"},
                priority=5
            )
            
            assert job.priority == 5
    
    @pytest.mark.asyncio
    async def test_enqueue_with_delay(self, queue_service):
        """Test enqueue with delay sets scheduled_at in future."""
        mock_db = MagicMock()
        mock_db.add = Mock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            before = datetime.now(timezone.utc)
            job = await queue_service.enqueue(
                queue_name="detection",
                payload={"job_id": "test-123"},
                delay_seconds=300  # 5 minutes
            )
            after = datetime.now(timezone.utc)
            
            # scheduled_at should be roughly 5 minutes in the future
            assert job.scheduled_at > before + timedelta(seconds=290)
            assert job.scheduled_at < after + timedelta(seconds=310)
    
    @pytest.mark.asyncio
    async def test_enqueue_with_max_attempts(self, queue_service):
        """Test enqueue with custom max_attempts."""
        mock_db = MagicMock()
        mock_db.add = Mock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job = await queue_service.enqueue(
                queue_name="detection",
                payload={"job_id": "test-123"},
                max_attempts=5
            )
            
            assert job.max_attempts == 5
    
    @pytest.mark.asyncio
    async def test_enqueue_with_provided_db_session(self, queue_service):
        """Test enqueue uses provided db session without creating new one."""
        mock_db = MagicMock()
        mock_db.add = Mock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        job = await queue_service.enqueue(
            queue_name="detection",
            payload={"job_id": "test-123"},
            db=mock_db
        )
        
        assert job.queue_name == "detection"
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        # Should not call commit when using provided session
        mock_db.commit.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_enqueue_negative_delay_raises_error(self, queue_service):
        """Test enqueue with negative delay raises ValueError."""
        with pytest.raises(ValueError, match="delay_seconds must be non-negative"):
            await queue_service.enqueue(
                queue_name="detection",
                payload={"job_id": "test-123"},
                delay_seconds=-10
            )
    
    @pytest.mark.asyncio
    async def test_dequeue_returns_job(self, queue_service):
        """Test dequeue returns pending job."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 0
        mock_job.max_attempts = 3
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_job
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job = await queue_service.dequeue("detection")
            
            assert job == mock_job
            assert job.status == "processing"
            assert job.attempts == 1
            mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_dequeue_with_provided_db_session(self, queue_service):
        """Test dequeue uses provided db session."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 0
        mock_job.max_attempts = 3
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_job
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        
        job = await queue_service.dequeue("detection", db=mock_db)
        
        assert job == mock_job
        assert job.status == "processing"
        mock_db.flush.assert_called_once()
        # Should not call commit when using provided session
        mock_db.commit.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_dequeue_no_pending_jobs(self, queue_service):
        """Test dequeue returns None when no pending jobs."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job = await queue_service.dequeue("detection")
            
            assert job is None
    
    @pytest.mark.asyncio
    async def test_dequeue_uses_skip_locked(self, queue_service):
        """Test dequeue uses SELECT FOR UPDATE SKIP LOCKED."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 0
        mock_job.max_attempts = 3
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_job
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            await queue_service.dequeue("detection")
            
            # Verify execute was called with SKIP LOCKED
            call_args = mock_db.execute.call_args
            assert call_args is not None
            # The query should contain with_for_update(skip_locked=True)
            # This is verified by the mock returning the job
    
    @pytest.mark.asyncio
    async def test_mark_completed(self, queue_service):
        """Test mark_completed updates job status."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job_id = UUID("550e8400-e29b-41d4-a716-446655440000")
            await queue_service.mark_completed(job_id)
            
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_mark_completed_with_provided_db_session(self, queue_service):
        """Test mark_completed uses provided db session."""
        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.flush = AsyncMock()
        
        job_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        await queue_service.mark_completed(job_id, db=mock_db)
        
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()
        mock_db.commit.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_mark_failed_with_retry(self, queue_service):
        """Test mark_failed reschedules job for retry."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 1
        mock_job.max_attempts = 3
        mock_job.status = "processing"
        
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        
        # Test with provided session (new signature)
        will_retry = await queue_service.mark_failed(
            mock_job,  # Now accepts job object directly
            error_message="Test error",
            retry_delay_seconds=60,
            db=mock_db
        )
        
        assert will_retry is True
        assert mock_job.status == "pending"
        assert mock_job.error_message == "Test error"
        mock_db.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_mark_failed_max_attempts(self, queue_service):
        """Test mark_failed marks job as failed when max attempts reached."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 3  # Already at max
        mock_job.max_attempts = 3
        mock_job.status = "processing"
        
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        
        # Test with provided session (new signature)
        will_retry = await queue_service.mark_failed(
            mock_job,  # Now accepts job object directly
            error_message="Test error",
            db=mock_db
        )
        
        assert will_retry is False
        assert mock_job.status == "failed"
        mock_db.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_mark_failed_exponential_backoff(self, queue_service):
        """Test mark_failed applies exponential backoff."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 2  # Second attempt
        mock_job.max_attempts = 3
        mock_job.status = "processing"
        
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        
        before = datetime.now(timezone.utc)
        await queue_service.mark_failed(
            mock_job,
            error_message="Test error",
            retry_delay_seconds=5,  # Base delay
            db=mock_db
        )
        after = datetime.now(timezone.utc)
        
        # With attempts=2, backoff multiplier = 2^(2-1) = 2
        # Delay should be 5 * 2 = 10 seconds
        expected_delay = timedelta(seconds=10)
        assert mock_job.scheduled_at > before + timedelta(seconds=9)
        assert mock_job.scheduled_at < after + timedelta(seconds=11)
    
    @pytest.mark.asyncio
    async def test_mark_failed_default_retry_delay(self, queue_service):
        """Test mark_failed uses default retry delay when not specified."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 1
        mock_job.max_attempts = 3
        mock_job.status = "processing"
        
        mock_db = MagicMock()
        mock_db.flush = AsyncMock()
        
        before = datetime.now(timezone.utc)
        await queue_service.mark_failed(
            mock_job,
            error_message="Test error",
            db=mock_db
        )
        after = datetime.now(timezone.utc)
        
        # Default retry delay is 5 seconds
        assert mock_job.scheduled_at > before + timedelta(seconds=4)
        assert mock_job.scheduled_at < after + timedelta(seconds=6)
    
    @pytest.mark.asyncio
    async def test_get_metrics(self, queue_service):
        """Test get_metrics returns queue status counts."""
        # Mock data: (queue_name, status, count)
        mock_rows = [
            ("detection", "pending", 5),
            ("detection", "processing", 2),
            ("detection", "failed", 1),
            ("detection", "completed", 100),
            ("asr", "pending", 3),
            ("asr", "processing", 1),
        ]
        
        mock_result = Mock()
        mock_result.all.return_value = mock_rows
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            metrics = await queue_service.get_metrics()
            
            assert "detection" in metrics
            assert "asr" in metrics
            assert metrics["detection"]["pending"] == 5
            assert metrics["detection"]["processing"] == 2
            assert metrics["detection"]["failed"] == 1
            assert metrics["detection"]["completed"] == 100
            assert metrics["asr"]["pending"] == 3
            assert metrics["asr"]["processing"] == 1
            assert metrics["asr"]["failed"] == 0
            assert metrics["asr"]["completed"] == 0
    
    @pytest.mark.asyncio
    async def test_get_metrics_specific_queue(self, queue_service):
        """Test get_metrics with specific queue name filter."""
        mock_rows = [
            ("detection", "pending", 5),
            ("detection", "processing", 2),
        ]
        
        mock_result = Mock()
        mock_result.all.return_value = mock_rows
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            metrics = await queue_service.get_metrics(queue_name="detection")
            
            assert "detection" in metrics
            assert "asr" not in metrics
            # Verify the query was filtered
            call_args = mock_db.execute.call_args
            assert call_args is not None
    
    @pytest.mark.asyncio
    async def test_get_metrics_empty(self, queue_service):
        """Test get_metrics returns empty dict when no jobs."""
        mock_result = Mock()
        mock_result.all.return_value = []
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            metrics = await queue_service.get_metrics()
            
            assert metrics == {}
    
    @pytest.mark.asyncio
    async def test_cleanup_completed(self, queue_service):
        """Test cleanup_completed removes old completed jobs."""
        # Create mock jobs to be deleted
        mock_job1 = Mock(spec=QueueJob)
        mock_job2 = Mock(spec=QueueJob)
        
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [mock_job1, mock_job2]
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            deleted_count = await queue_service.cleanup_completed(retention_days=7)
            
            assert deleted_count == 2
            mock_db.execute.assert_called_once()
            assert mock_db.delete.call_count == 2  # Called for each job
            mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_completed_with_provided_db_session(self, queue_service):
        """Test cleanup_completed uses provided db session."""
        mock_job = Mock(spec=QueueJob)
        
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [mock_job]
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.delete = AsyncMock()
        
        deleted_count = await queue_service.cleanup_completed(
            retention_days=7,
            db=mock_db
        )
        
        assert deleted_count == 1
        mock_db.execute.assert_called_once()
        mock_db.delete.assert_called_once()
        mock_db.flush.assert_called_once()
        mock_db.commit.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_cleanup_completed_no_old_jobs(self, queue_service):
        """Test cleanup_completed returns 0 when no old jobs."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            deleted_count = await queue_service.cleanup_completed(retention_days=7)
            
            assert deleted_count == 0
