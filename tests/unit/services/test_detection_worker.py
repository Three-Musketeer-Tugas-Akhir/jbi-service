"""Tests for detection worker."""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
from uuid import UUID

from app.services.detection_worker import DetectionWorker, get_detection_worker
from app.db.models.pipeline import QueueJob, PipelineSegment
from app.core.exceptions import ProcessingError


class TestDetectionWorker:
    """Test suite for detection worker."""
    
    @pytest.fixture
    def worker(self):
        """Create detection worker."""
        with patch('app.services.detection_worker.get_minio_service'), \
             patch('app.services.detection_worker.get_jbi_detector'), \
             patch('app.services.detection_worker.signal'):
            return DetectionWorker()
    
    @pytest.mark.asyncio
    async def test_process_job_success(self, worker):
        """Test successful job processing flow."""
        # Setup mocks
        mock_job_repo = AsyncMock()
        mock_segment_repo = AsyncMock()
        mock_queue_job = Mock(spec=QueueJob)
        mock_queue_job.payload = {"job_id": "550e8400-e29b-41d4-a716-446655440000"}
        
        mock_job = Mock()
        mock_job.video_path = "jobs/test/original/video.mp4"
        mock_job_repo.get_by_id.return_value = mock_job
        
        # Mock segments
        mock_segment = Mock(spec=JBISegment)
        mock_segment.bbox_data = {"x": 100, "y": 100, "width": 200, "height": 150}
        mock_segment.start_time = 5.0
        mock_segment.end_time = 10.0
        
        with patch('app.services.detection_worker.get_db_session') as mock_db_session, \
             patch.object(worker, '_download_video') as mock_download, \
             patch.object(worker.detector, 'detect') as mock_detect, \
             patch.object(worker, '_process_segments') as mock_process, \
             patch('app.services.detection_worker.queue_service') as mock_queue:
            
            mock_db = AsyncMock()
            mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            mock_download.return_value = Path("/tmp/test.mp4")
            mock_detect.return_value = [mock_segment]
            mock_process.return_value = [Mock(spec=PipelineSegment)]
            
            await worker._process_job(mock_queue_job)
            
            # Verify status updates
            mock_job_repo.update_status.assert_any_call(
                UUID("550e8400-e29b-41d4-a716-446655440000"), "DETECTING"
            )
            mock_job_repo.update_status.assert_any_call(
                UUID("550e8400-e29b-41d4-a716-446655440000"), "TRANSCRIBING"
            )
            
            # Verify queue operations
            mock_queue.enqueue.assert_called_once()
            mock_queue.mark_completed.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_job_no_detections(self, worker):
        """Test handling of no detections."""
        mock_job_repo = AsyncMock()
        mock_queue_job = Mock(spec=QueueJob)
        mock_queue_job.payload = {"job_id": "550e8400-e29b-41d4-a716-446655440000"}
        
        mock_job = Mock()
        mock_job.video_path = "jobs/test/original/video.mp4"
        mock_job_repo.get_by_id.return_value = mock_job
        
        with patch('app.services.detection_worker.get_db_session') as mock_db_session, \
             patch.object(worker, '_download_video') as mock_download, \
             patch.object(worker.detector, 'detect') as mock_detect, \
             patch.object(worker, '_handle_failure') as mock_handle_failure:
            
            mock_db = AsyncMock()
            mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            mock_download.return_value = Path("/tmp/test.mp4")
            mock_detect.return_value = []  # No detections
            
            await worker._process_job(mock_queue_job)
            
            # Verify failure handling
            mock_handle_failure.assert_called_once()
            call_args = mock_handle_failure.call_args
            assert "No JBI regions detected" in call_args[0][3]
    
    @pytest.mark.asyncio
    async def test_process_job_job_not_found(self, worker):
        """Test handling when job not found in database."""
        mock_job_repo = AsyncMock()
        mock_queue_job = Mock(spec=QueueJob)
        mock_queue_job.payload = {"job_id": "550e8400-e29b-41d4-a716-446655440000"}
        
        mock_job_repo.get_by_id.return_value = None
        
        with patch('app.services.detection_worker.get_db_session') as mock_db_session, \
             patch.object(worker, '_handle_failure') as mock_handle_failure:
            
            mock_db = AsyncMock()
            mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            await worker._process_job(mock_queue_job)
            
            mock_handle_failure.assert_called_once()
            call_args = mock_handle_failure.call_args
            assert "not found" in call_args[0][3]
    
    @pytest.mark.asyncio
    async def test_download_video_success(self, worker):
        """Test successful video download."""
        with patch.object(worker.minio_service, 'download_file') as mock_download:
            mock_download.return_value = b"video data"
            
            path = await worker._download_video(
                UUID("550e8400-e29b-41d4-a716-446655440000"),
                "jobs/test/original/video.mp4"
            )
            
            assert path.exists()
            assert path.suffix == ".mp4"
            assert "detection_" in path.name
            mock_download.assert_called_once_with("jobs/test/original/video.mp4")
    
    @pytest.mark.asyncio
    async def test_download_video_failure(self, worker):
        """Test video download failure raises ProcessingError."""
        with patch.object(worker.minio_service, 'download_file') as mock_download:
            mock_download.side_effect = Exception("Download failed")
            
            with pytest.raises(ProcessingError, match="Failed to download"):
                await worker._download_video(
                    UUID("550e8400-e29b-41d4-a716-446655440000"),
                    "jobs/test/original/video.mp4"
                )
    
    @pytest.mark.asyncio
    async def test_cleanup_temp_video(self, worker):
        """Test temporary video cleanup."""
        # Create temp file
        temp_path = Path("/tmp/test_cleanup.mp4")
        temp_path.write_bytes(b"test")
        assert temp_path.exists()
        
        await worker._cleanup_temp_video(temp_path)
        
        assert not temp_path.exists()
    
    @pytest.mark.asyncio
    async def test_cleanup_temp_video_nonexistent(self, worker):
        """Test cleanup handles non-existent file gracefully."""
        temp_path = Path("/tmp/nonexistent.mp4")
        
        # Should not raise
        await worker._cleanup_temp_video(temp_path)
    
    @pytest.mark.asyncio
    async def test_handle_failure(self, worker):
        """Test failure handling updates status and marks queue job failed."""
        mock_job_repo = AsyncMock()
        mock_queue_job = Mock(spec=QueueJob)
        mock_queue_job.payload = {"job_id": "550e8400-e29b-41d4-a716-446655440000"}
        mock_db = AsyncMock()
        
        with patch('app.services.detection_worker.queue_service') as mock_queue:
            await worker._handle_failure(
                mock_db, mock_job_repo, mock_queue_job, "Test error"
            )
            
            mock_job_repo.update_status.assert_called_once_with(
                UUID("550e8400-e29b-41d4-a716-446655440000"),
                "FAILED",
                "Test error"
            )
            mock_queue.mark_failed.assert_called_once()
    
    def test_handle_shutdown(self, worker):
        """Test shutdown handler sets running to False."""
        worker.running = True
        
        worker._handle_shutdown(15, None)  # SIGTERM
        
        assert worker.running is False
    
    @pytest.mark.asyncio
    async def test_start_polls_queue(self, worker):
        """Test worker loop polls queue."""
        worker.running = True
        
        with patch('app.services.detection_worker.queue_service') as mock_queue, \
             patch('asyncio.sleep') as mock_sleep:
            
            # Stop after one iteration
            mock_queue.dequeue.return_value = None
            mock_sleep.side_effect = [None, Exception("Stop")]
            
            with pytest.raises(Exception, match="Stop"):
                await worker.start()
            
            mock_queue.dequeue.assert_called_with("detection")


class TestJBISegmentMock:
    """Mock JBISegment for testing."""
    pass
