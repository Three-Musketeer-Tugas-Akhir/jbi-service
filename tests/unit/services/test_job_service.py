"""Tests for job service."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from uuid import UUID

from app.core.exceptions import ValidationError
from app.db.models.auth import User
from app.db.models.pipeline import PipelineJob
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService


class TestJobService:
    """Test suite for job service."""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()
    
    @pytest.fixture
    def mock_job_repo(self):
        """Mock job repository."""
        repo = AsyncMock(spec=JobRepository)
        return repo
    
    @pytest.fixture
    def mock_user(self):
        """Mock user."""
        user = Mock(spec=User)
        user.id = UUID("550e8400-e29b-41d4-a716-446655440000")
        return user
    
    @pytest.fixture
    def job_service(self, mock_db, mock_job_repo):
        """Create job service with mocked dependencies."""
        with patch('app.services.job_service.get_minio_service') as mock_minio:
            mock_minio.return_value = AsyncMock()
            service = JobService(mock_db, mock_job_repo)
            return service
    
    def test_validate_file_supported_format(self, job_service):
        """Test validation passes for supported format."""
        # Should not raise
        job_service._validate_file("video.mp4", 1024 * 1024)  # 1MB
        job_service._validate_file("video.avi", 1024 * 1024)
        job_service._validate_file("video.mkv", 1024 * 1024)
        job_service._validate_file("video.mov", 1024 * 1024)
    
    def test_validate_file_unsupported_format(self, job_service):
        """Test validation fails for unsupported format."""
        with pytest.raises(ValidationError) as exc_info:
            job_service._validate_file("video.wmv", 1024 * 1024)
        
        assert "Unsupported file format" in str(exc_info.value)
        assert ".wmv" in str(exc_info.value.details["filename"])
    
    def test_validate_file_too_large(self, job_service):
        """Test validation fails for file too large."""
        # 11GB
        file_size = 11 * 1024 * 1024 * 1024
        
        with pytest.raises(ValidationError) as exc_info:
            job_service._validate_file("video.mp4", file_size)
        
        assert "File too large" in str(exc_info.value)
        assert exc_info.value.details["file_size"] == file_size
        assert exc_info.value.details["max_size"] == job_service.MAX_FILE_SIZE
    
    @pytest.mark.asyncio
    async def test_create_job_from_upload_success(
        self, job_service, mock_job_repo, mock_user
    ):
        """Test successful job creation from upload."""
        # Setup
        mock_job = Mock(spec=PipelineJob)
        mock_job.id = UUID("660e8400-e29b-41d4-a716-446655440001")
        mock_job.status = "QUEUED"
        mock_job.original_filename = "test.mp4"
        mock_job.file_size = 1024 * 1024
        mock_job.created_at = Mock()
        
        mock_job_repo.create.return_value = mock_job
        
        with patch('app.services.job_service.queue_service') as mock_queue:
            mock_queue.enqueue = AsyncMock()
            
            # Execute
            job = await job_service.create_job_from_upload(
                filename="test.mp4",
                file_data=b"test video data",
                file_size=1024 * 1024,
                user=mock_user
            )
            
            # Verify
            assert job == mock_job
            mock_job_repo.create.assert_called_once()
            job_service.minio_service.upload_job_video.assert_called_once()
            mock_queue.enqueue.assert_called_once_with(
                queue_name="detection",
                payload={
                    "job_id": str(mock_job.id),
                    "stage": "detection"
                }
            )
            mock_job_repo.update_status.assert_called_once_with(
                mock_job.id, "QUEUED"
            )
    
    @pytest.mark.asyncio
    async def test_create_job_from_upload_invalid_format(
        self, job_service, mock_job_repo, mock_user
    ):
        """Test job creation fails for invalid format."""
        with pytest.raises(ValidationError):
            await job_service.create_job_from_upload(
                filename="video.wmv",
                file_data=b"test",
                file_size=1024,
                user=mock_user
            )
        
        # Should not create job or upload
        mock_job_repo.create.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_create_job_from_url_not_implemented(
        self, job_service, mock_user
    ):
        """Test URL upload raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await job_service.create_job_from_url(
                video_url="https://example.com/video.mp4",
                user=mock_user
            )
