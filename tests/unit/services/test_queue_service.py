"""Tests for queue service."""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
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
            
            before = datetime.utcnow()
            job = await queue_service.enqueue(
                queue_name="detection",
                payload={"job_id": "test-123"},
                delay_seconds=300  # 5 minutes
            )
            after = datetime.utcnow()
            
            # scheduled_at should be roughly 5 minutes in the future
            assert job.scheduled_at > before + timedelta(seconds=290)
            assert job.scheduled_at < after + timedelta(seconds=310)
    
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
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job = await queue_service.dequeue("detection")
            
            assert job == mock_job
            assert job.status == "processing"
            assert job.attempts == 1
            mock_db.commit.assert_called_once()
    
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
    async def test_mark_failed_with_retry(self, queue_service):
        """Test mark_failed reschedules job for retry."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 1
        mock_job.max_attempts = 3
        mock_job.status = "processing"
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_job
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job_id = UUID("550e8400-e29b-41d4-a716-446655440000")
            await queue_service.mark_failed(
                job_id,
                error_message="Test error",
                retry_delay_seconds=60
            )
            
            assert mock_job.status == "pending"
            assert mock_job.error_message == "Test error"
            mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_mark_failed_max_attempts(self, queue_service):
        """Test mark_failed marks job as failed when max attempts reached."""
        mock_job = Mock(spec=QueueJob)
        mock_job.attempts = 3  # Already at max
        mock_job.max_attempts = 3
        mock_job.status = "processing"
        
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_job
        
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        
        with patch('app.services.queue_service.get_db_session') as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            job_id = UUID("550e8400-e29b-41d4-a716-446655440000")
            await queue_service.mark_failed(
                job_id,
                error_message="Test error"
            )
            
            assert mock_job.status == "failed"
            mock_db.commit.assert_called_once()
