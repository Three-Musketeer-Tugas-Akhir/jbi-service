"""Integration tests for MinIO storage.

These tests require a running MinIO instance.
Mark with pytest.mark.integration to skip by default.
"""

import pytest
import uuid

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_minio_full_workflow():
    """Test complete upload-download-delete workflow."""
    from app.services.minio_service import MinIOService
    
    # Arrange
    service = MinIOService()
    test_content = b"Integration test video content"
    object_name = f"test/{uuid.uuid4()}/video.mp4"
    
    try:
        # Act - Upload
        result = await service.upload_file(test_content, object_name)
        assert result == object_name
        
        # Act - Check exists
        exists = await service.object_exists(object_name)
        assert exists is True
        
        # Act - Get size
        size = await service.get_object_size(object_name)
        assert size == len(test_content)
        
        # Act - Generate URL
        url = await service.generate_presigned_url(object_name)
        assert url.startswith("http")
        
        # Act - Download
        downloaded = await service.download_file(object_name)
        assert downloaded == test_content
        
    finally:
        # Cleanup
        await service.delete_object(object_name)
        
        # Verify deleted
        exists = await service.object_exists(object_name)
        assert exists is False


@pytest.mark.asyncio
async def test_job_video_upload():
    """Test job video upload helper."""
    from app.services.minio_service import MinIOService
    
    service = MinIOService()
    job_id = str(uuid.uuid4())
    
    try:
        result = await service.upload_job_video(
            job_id,
            b"test video",
            "original.mp4"
        )
        
        assert f"jobs/{job_id}/original/original.mp4" == result
        
    finally:
        # Cleanup
        await service.delete_object(f"jobs/{job_id}/original/original.mp4")


@pytest.mark.asyncio
async def test_segment_upload_stage1():
    """Test segment upload for stage1."""
    from app.services.minio_service import MinIOService
    
    service = MinIOService()
    job_id = str(uuid.uuid4())
    
    try:
        result = await service.upload_segment(
            job_id,
            0,
            b"stage1 segment",
            stage="stage1"
        )
        
        assert f"jobs/{job_id}/stage1/segment_0.mp4" == result
        
    finally:
        # Cleanup
        await service.delete_object(f"jobs/{job_id}/stage1/segment_0.mp4")


@pytest.mark.asyncio
async def test_segment_upload_final():
    """Test segment upload for final stage."""
    from app.services.minio_service import MinIOService
    
    service = MinIOService()
    job_id = str(uuid.uuid4())
    
    try:
        result = await service.upload_segment(
            job_id,
            1,
            b"final segment",
            stage="final"
        )
        
        assert f"jobs/{job_id}/segments/1.mp4" == result
        
    finally:
        # Cleanup
        await service.delete_object(f"jobs/{job_id}/segments/1.mp4")


@pytest.mark.asyncio
async def test_get_segment_url():
    """Test getting pre-signed URL for segment."""
    from app.services.minio_service import MinIOService
    
    service = MinIOService()
    job_id = str(uuid.uuid4())
    
    try:
        # Upload a segment first
        await service.upload_segment(
            job_id,
            0,
            b"test segment",
            stage="final"
        )
        
        # Get URL
        url = await service.get_segment_url(job_id, 0, stage="final")
        assert url.startswith("http")
        assert "jobs/" in url
        
    finally:
        # Cleanup
        await service.delete_object(f"jobs/{job_id}/segments/0.mp4")


@pytest.mark.asyncio
async def test_object_not_exists():
    """Test checking non-existent object."""
    from app.services.minio_service import MinIOService
    
    service = MinIOService()
    object_name = f"test/{uuid.uuid4()}/nonexistent.mp4"
    
    exists = await service.object_exists(object_name)
    assert exists is False
