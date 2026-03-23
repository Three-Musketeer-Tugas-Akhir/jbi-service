"""Tests for MinIO service."""

import pytest
from unittest.mock import Mock, patch
from minio.error import S3Error

from app.core.exceptions import StorageError, StorageUnavailableError


# Import MinIOService at module level but it will be patched in fixture
from app.services.minio_service import MinIOService


class TestMinIOService:
    """Test suite for MinIO service."""
    
    @pytest.fixture(autouse=True)
    def reset_and_patch(self, monkeypatch):
        """Reset singleton and patch MinIO client for each test."""
        # Reset singleton state before each test
        MinIOService._instance = None
        MinIOService._client = None
        MinIOService._initialized = False
        
        # Create mock client
        mock_client = Mock()
        mock_client.bucket_exists.return_value = True
        
        # Patch Minio class
        with patch('app.services.minio_service.Minio', return_value=mock_client):
            yield mock_client
        
        # Cleanup after test
        MinIOService._instance = None
        MinIOService._client = None
        MinIOService._initialized = False
    
    @pytest.fixture
    def minio_service(self, reset_and_patch):
        """Create fresh MinIO service with mocked client."""
        # Reset before creating new instance
        MinIOService._instance = None
        MinIOService._client = None
        MinIOService._initialized = False
        return MinIOService()
    
    @pytest.mark.asyncio
    async def test_upload_file_success(self, minio_service, reset_and_patch):
        """Test successful file upload."""
        mock_client = reset_and_patch
        file_data = b"test video content"
        object_name = "jobs/test/video.mp4"
        
        result = await minio_service.upload_file(file_data, object_name)
        
        assert result == object_name
        mock_client.put_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_upload_file_failure(self, minio_service, reset_and_patch):
        """Test file upload failure."""
        mock_client = reset_and_patch
        mock_client.put_object.side_effect = S3Error(
            "Mock error", "InternalError", None, None, None, None
        )
        
        with pytest.raises(StorageError):
            await minio_service.upload_file(b"data", "test.mp4")
    
    @pytest.mark.asyncio
    async def test_generate_presigned_url(self, minio_service, reset_and_patch):
        """Test pre-signed URL generation."""
        mock_client = reset_and_patch
        mock_client.presigned_get_object.return_value = "http://minio/test-url"
        
        url = await minio_service.generate_presigned_url("test.mp4")
        
        assert url == "http://minio/test-url"
        mock_client.presigned_get_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_object_exists_true(self, minio_service, reset_and_patch):
        """Test object exists check - True case."""
        mock_client = reset_and_patch
        mock_client.stat_object.return_value = Mock(size=1024)
        
        exists = await minio_service.object_exists("test.mp4")
        
        assert exists is True
    
    @pytest.mark.asyncio
    async def test_object_exists_false(self, minio_service, reset_and_patch):
        """Test object exists check - False case."""
        mock_client = reset_and_patch
        mock_client.stat_object.side_effect = S3Error(
            "Not found", "NoSuchKey", None, None, None, None
        )
        
        exists = await minio_service.object_exists("test.mp4")
        
        assert exists is False
    
    @pytest.mark.asyncio
    async def test_upload_job_video(self, minio_service, reset_and_patch):
        """Test uploading job video."""
        mock_client = reset_and_patch
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        file_data = b"video content"
        filename = "news.mp4"
        
        result = await minio_service.upload_job_video(
            job_id, file_data, filename
        )
        
        expected_path = f"jobs/{job_id}/original/{filename}"
        assert result == expected_path
        mock_client.put_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_upload_segment_stage1(self, minio_service, reset_and_patch):
        """Test uploading segment - stage1."""
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        file_data = b"segment content"
        
        result = await minio_service.upload_segment(
            job_id, 0, file_data, stage="stage1"
        )
        
        assert f"jobs/{job_id}/stage1/segment_0.mp4" == result
    
    @pytest.mark.asyncio
    async def test_upload_segment_final(self, minio_service, reset_and_patch):
        """Test uploading segment - final stage."""
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        file_data = b"segment content"
        
        result = await minio_service.upload_segment(
            job_id, 1, file_data, stage="final"
        )
        
        assert f"jobs/{job_id}/segments/1.mp4" == result
    
    @pytest.mark.asyncio
    async def test_download_file_success(self, minio_service, reset_and_patch):
        """Test successful file download."""
        mock_client = reset_and_patch
        mock_response = Mock()
        mock_response.read.return_value = b"downloaded content"
        mock_client.get_object.return_value = mock_response
        
        result = await minio_service.download_file("test.mp4")
        
        assert result == b"downloaded content"
        mock_client.get_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_download_file_failure(self, minio_service, reset_and_patch):
        """Test file download failure."""
        mock_client = reset_and_patch
        mock_client.get_object.side_effect = S3Error(
            "Not found", "NoSuchKey", None, None, None, None
        )
        
        with pytest.raises(StorageError):
            await minio_service.download_file("test.mp4")
    
    @pytest.mark.asyncio
    async def test_delete_object_success(self, minio_service, reset_and_patch):
        """Test successful object deletion."""
        mock_client = reset_and_patch
        
        await minio_service.delete_object("test.mp4")
        
        mock_client.remove_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_object_size(self, minio_service, reset_and_patch):
        """Test getting object size."""
        mock_client = reset_and_patch
        mock_stat = Mock()
        mock_stat.size = 1024
        mock_client.stat_object.return_value = mock_stat
        
        size = await minio_service.get_object_size("test.mp4")
        
        assert size == 1024
    
    @pytest.mark.asyncio
    async def test_get_segment_url_stage1(self, minio_service, reset_and_patch):
        """Test getting segment URL for stage1."""
        mock_client = reset_and_patch
        mock_client.presigned_get_object.return_value = "http://minio/segment-url"
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        
        url = await minio_service.get_segment_url(job_id, 0, stage="stage1")
        
        assert url == "http://minio/segment-url"
        mock_client.presigned_get_object.assert_called_once_with(
            bucket_name="anotasi-videos",
            object_name=f"jobs/{job_id}/stage1/segment_0.mp4",
            expires=3600
        )
    
    @pytest.mark.asyncio
    async def test_get_segment_url_final(self, minio_service, reset_and_patch):
        """Test getting segment URL for final stage."""
        mock_client = reset_and_patch
        mock_client.presigned_get_object.return_value = "http://minio/segment-url"
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        
        url = await minio_service.get_segment_url(job_id, 0, stage="final")
        
        assert url == "http://minio/segment-url"
        mock_client.presigned_get_object.assert_called_once_with(
            bucket_name="anotasi-videos",
            object_name=f"jobs/{job_id}/segments/0.mp4",
            expires=3600
        )
    
    def test_bucket_creation_on_init(self, reset_and_patch):
        """Test bucket is created on service initialization if it doesn't exist."""
        mock_client = reset_and_patch
        mock_client.bucket_exists.return_value = False
        
        # Reset singleton
        MinIOService._instance = None
        MinIOService._client = None
        MinIOService._initialized = False
        
        service = MinIOService()
        
        mock_client.bucket_exists.assert_called_once()
        mock_client.make_bucket.assert_called_once()
    
    def test_bucket_exists_no_creation(self, reset_and_patch):
        """Test bucket is not created if it already exists."""
        mock_client = reset_and_patch
        mock_client.bucket_exists.return_value = True
        
        # Reset singleton
        MinIOService._instance = None
        MinIOService._client = None
        MinIOService._initialized = False
        
        service = MinIOService()
        
        mock_client.bucket_exists.assert_called_once()
        mock_client.make_bucket.assert_not_called()
