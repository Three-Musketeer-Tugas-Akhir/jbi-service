"""Tests for ASR worker service."""

from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from uuid import uuid4, UUID

import pytest

from app.services.asr_worker import ASRWorker, get_asr_worker, run_asr_worker
from app.core.exceptions import ProcessingError
from app.db.models.pipeline import PipelineSegment, QueueJob, JobStatus


class TestASRWorker:
    """Test suite for ASR worker."""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        import app.services.asr_worker as asr_worker_module
        asr_worker_module._asr_worker_instance = None
        yield
        asr_worker_module._asr_worker_instance = None
    
    @pytest.fixture
    def worker(self):
        """Create ASR worker instance with mocked dependencies."""
        with patch("app.services.asr_worker.get_minio_service"), \
             patch("app.services.asr_worker.get_transcriber_service"), \
             patch("app.services.asr_worker.get_audio_extractor"):
            worker = ASRWorker(poll_interval=1, timeout_seconds=30)
            yield worker
    
    @pytest.fixture
    def mock_segment(self):
        """Create a mock pipeline segment."""
        segment = Mock(spec=PipelineSegment)
        segment.id = uuid4()
        segment.segment_index = 0
        segment.cropped_video_path = "jobs/test-job/stage1/segment_0.mp4"
        segment.asr_text = None
        segment.asr_start = None
        segment.asr_end = None
        segment.asr_confidence = None
        return segment
    
    @pytest.fixture
    def mock_queue_job(self):
        """Create a mock queue job."""
        job = Mock(spec=QueueJob)
        job.id = uuid4()
        job.payload = {"job_id": str(uuid4())}
        return job
    
    def test_singleton_pattern(self):
        """Test that get_asr_worker returns singleton."""
        with patch("app.services.asr_worker.get_minio_service"), \
             patch("app.services.asr_worker.get_transcriber_service"), \
             patch("app.services.asr_worker.get_audio_extractor"):
            worker1 = get_asr_worker()
            worker2 = get_asr_worker()
            assert worker1 is worker2
    
    def test_initialization(self, worker):
        """Test worker initialization."""
        assert worker.poll_interval == 1
        assert worker.timeout_seconds == 30
        assert worker.running is True  # running is True when shutdown_event is not set
    
    @pytest.mark.asyncio
    async def test_handle_shutdown(self, worker):
        """Test shutdown signal handler."""
        assert not worker._shutdown_event.is_set()
        worker._handle_shutdown(15, None)  # SIGTERM = 15
        assert worker._shutdown_event.is_set()
        assert worker.running is False
    
    @pytest.mark.asyncio
    async def test_download_segment(self, worker):
        """Test segment download from MinIO."""
        worker.minio_service.download_file = AsyncMock(return_value=b"video data")
        
        result = await worker._download_segment("path/to/segment.mp4")
        
        assert result == b"video data"
        worker.minio_service.download_file.assert_called_once_with("path/to/segment.mp4")
    
    @pytest.mark.asyncio
    async def test_download_segment_failure(self, worker):
        """Test segment download failure handling."""
        worker.minio_service.download_file = AsyncMock(
            side_effect=Exception("MinIO error")
        )
        
        with pytest.raises(ProcessingError) as exc_info:
            await worker._download_segment("path/to/segment.mp4")
        
        assert "Failed to download segment" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_save_temp_video(self, worker):
        """Test saving video data to temp file."""
        video_data = b"test video content"
        
        path = await worker._save_temp_video(video_data, 0)
        
        assert path.exists()
        assert path.read_bytes() == video_data
        assert "asr_segment_0_" in path.name
        
        # Cleanup
        path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_cleanup_temp_files(self, worker, tmp_path):
        """Test cleanup of temporary files."""
        video_path = tmp_path / "video.mp4"
        audio_path = tmp_path / "audio.wav"
        video_path.write_text("video")
        audio_path.write_text("audio")
        
        await worker._cleanup_temp_files(video_path, audio_path)
        
        assert not video_path.exists()
        assert not audio_path.exists()
    
    @pytest.mark.asyncio
    async def test_cleanup_temp_files_handles_missing(self, worker, tmp_path):
        """Test cleanup handles missing files gracefully."""
        non_existent_path = tmp_path / "does_not_exist.mp4"
        
        # Should not raise
        await worker._cleanup_temp_files(non_existent_path, None)
    
    @pytest.mark.asyncio
    async def test_process_segment_success(self, worker, mock_segment):
        """Test successful segment processing."""
        job_id = uuid4()
        
        # Setup mocks
        worker.minio_service.download_file = AsyncMock(return_value=b"video data")
        worker._save_temp_video = AsyncMock(return_value=Path("/tmp/video.mp4"))
        worker.audio_extractor.extract = AsyncMock(return_value=Path("/tmp/audio.wav"))
        
        mock_result = Mock()
        mock_result.text = "transcribed text"
        mock_result.start = 1.0
        mock_result.end = 5.0
        mock_result.average_confidence = 0.85
        mock_result.segments = [Mock()]
        worker.transcriber.transcribe = AsyncMock(return_value=mock_result)
        
        mock_db = AsyncMock()
        
        # Process segment
        result = await worker._process_segment(mock_db, job_id, mock_segment)
        
        # Verify
        assert result is True
        assert mock_segment.asr_text == "transcribed text"
        assert mock_segment.asr_start == 1.0
        assert mock_segment.asr_end == 5.0
        assert mock_segment.asr_confidence == 0.85
        mock_db.flush.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_segment_low_confidence(self, worker, mock_segment):
        """Test low confidence flagging."""
        job_id = uuid4()
        
        # Setup mocks with low confidence
        worker.minio_service.download_file = AsyncMock(return_value=b"video data")
        worker._save_temp_video = AsyncMock(return_value=Path("/tmp/video.mp4"))
        worker.audio_extractor.extract = AsyncMock(return_value=Path("/tmp/audio.wav"))
        
        mock_result = Mock()
        mock_result.text = "unclear text"
        mock_result.start = 1.0
        mock_result.end = 5.0
        mock_result.average_confidence = 0.3  # Low confidence
        mock_result.segments = [Mock()]
        worker.transcriber.transcribe = AsyncMock(return_value=mock_result)
        
        mock_db = AsyncMock()
        
        # Process segment
        result = await worker._process_segment(mock_db, job_id, mock_segment)
        
        # Should succeed but with low confidence
        assert result is True
        assert mock_segment.asr_confidence == 0.3
    
    @pytest.mark.asyncio
    async def test_process_segment_failure(self, worker, mock_segment):
        """Test segment processing failure handling."""
        job_id = uuid4()
        
        # Setup mocks to fail
        worker.minio_service.download_file = AsyncMock(
            side_effect=Exception("Download failed")
        )
        
        mock_db = AsyncMock()
        
        # Process segment
        result = await worker._process_segment(mock_db, job_id, mock_segment)
        
        # Should return False on failure
        assert result is False
        assert mock_segment.asr_text is None
        assert mock_segment.asr_confidence == 0.0
    
    @pytest.mark.asyncio
    async def test_handle_failure(self, worker, mock_queue_job):
        """Test job failure handling."""
        mock_db = AsyncMock()
        mock_job_repo = Mock()
        mock_job_repo.update_status = AsyncMock()
        
        with patch("app.services.asr_worker.queue_service") as mock_queue_service:
            mock_queue_service.mark_failed = AsyncMock()
            
            await worker._handle_failure(
                mock_db, mock_job_repo, mock_queue_job, "Test error"
            )
            
            # Verify status updated
            mock_job_repo.update_status.assert_called_once()
            args = mock_job_repo.update_status.call_args[0]
            assert args[1] == JobStatus.FAILED
            assert args[2] == "Test error"
