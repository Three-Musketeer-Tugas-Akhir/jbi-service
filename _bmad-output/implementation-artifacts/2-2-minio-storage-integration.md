---
story_id: "2.2"
story_key: "2-2-minio-storage-integration"
epic: 2
status: ready-for-dev
created: "2026-03-24"
last_updated: "2026-03-24"
---

# Story 2.2: MinIO Storage Integration

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.2  
**Status:** ready-for-dev  
**Priority:** Critical (Foundation)  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅

---

## Story Requirements

### User Story

As a developer,  
I want to integrate MinIO for video storage,  
So that video files can be uploaded and retrieved securely.

### Business Context

This story establishes the object storage layer for the video processing pipeline. MinIO provides S3-compatible storage for video files, enabling scalable storage with pre-signed URL access. This is a foundational component required for all subsequent Epic 2 stories that handle video files.

### Acceptance Criteria

**Given** MinIO is configured (endpoint, access_key, secret_key, bucket_name)  
**When** I call `minio_service.upload_file(file_data, object_name)`  
**Then** the file is uploaded to the configured bucket  
**And** the object_name follows pattern: `jobs/{job_id}/{filename}`

**Given** a file exists in MinIO  
**When** I call `minio_service.generate_presigned_url(object_name, expiry=3600)`  
**Then** a pre-signed URL is returned valid for 1 hour  
**And** the URL allows direct download without API authentication

**Given** a job is complete and segments are stored  
**When** I call `minio_service.get_segment_url(job_id, segment_index)`  
**Then** a pre-signed URL for the specific segment is returned

**Given** MinIO is unavailable  
**When** attempting upload or download  
**Then** appropriate error is raised with retry information

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: Endpoints use MinIO service for file operations
   - **Service Layer**: `minio_service.py` handles all MinIO operations
   - **Repository Layer**: (Not applicable - direct service usage)
   - **Pipeline Layer**: Workers use MinIO service for video I/O

2. **Storage Patterns**
   - Use MinIO for all video file storage (not local filesystem)
   - Pre-signed URLs for client access (1-hour expiry per NFR10)
   - Object naming: `jobs/{job_id}/{filename}`
   - Segment naming: `jobs/{job_id}/segments/{segment_index}.mp4`

3. **Error Handling**
   - Transient errors: Network issues, temporary unavailability
   - Permanent errors: Authentication failure, bucket not found
   - All errors include context for debugging

### Technical Requirements

**MinIO Configuration:**
```python
# Configuration variables (add to config.py)
MINIO_ENDPOINT = "localhost:9000"  # or minio:9000 in Docker
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
MINIO_BUCKET_NAME = "anotasi-videos"
MINIO_SECURE = False  # True for production with TLS
MINIO_REGION = "us-east-1"
```

**Object Naming Conventions:**
```
# Original uploads
jobs/{job_id}/original/{original_filename}

# Stage 1 cropped segments (from detection)
jobs/{job_id}/stage1/segment_{index}.mp4

# Stage 2 final cropped segments (JBI buffer applied)
jobs/{job_id}/segments/{index}.mp4

# Examples:
jobs/550e8400-e29b-41d4-a716-446655440000/original/news_video.mp4
jobs/550e8400-e29b-41d4-a716-446655440000/stage1/segment_0.mp4
jobs/550e8400-e29b-41d4-a716-446655440000/segments/0.mp4
```

**Service Interface:**
```python
class MinIOService:
    async def upload_file(
        self, 
        file_data: bytes | BinaryIO, 
        object_name: str,
        content_type: str = "video/mp4"
    ) -> str:
        """Upload file to MinIO, return object_name."""
        
    async def download_file(
        self, 
        object_name: str
    ) -> bytes:
        """Download file from MinIO as bytes."""
        
    async def generate_presigned_url(
        self, 
        object_name: str, 
        expiry: int = 3600
    ) -> str:
        """Generate pre-signed URL for direct access."""
        
    async def get_segment_url(
        self,
        job_id: str,
        segment_index: int,
        stage: str = "final"  # "stage1" or "final"
    ) -> str:
        """Get pre-signed URL for a specific segment."""
        
    async def delete_object(
        self, 
        object_name: str
    ) -> None:
        """Delete object from MinIO."""
        
    async def object_exists(
        self, 
        object_name: str
    ) -> bool:
        """Check if object exists in bucket."""
        
    async def get_object_size(
        self,
        object_name: str
    ) -> int:
        """Get object size in bytes."""
```

---

## Implementation Guide

### Phase 1: Add MinIO Configuration

#### Step 1.1: Update app/config.py

```python
# Add to Settings class:

# --- MinIO / S3 Storage ---
minio_endpoint: str = "localhost:9000"
minio_access_key: str = "minioadmin"
minio_secret_key: str = "minioadmin"
minio_bucket_name: str = "anotasi-videos"
minio_secure: bool = False  # Set True for HTTPS
minio_region: str = "us-east-1"
minio_presigned_url_expiry: int = 3600  # 1 hour (NFR10)

@property
def minio_endpoint_url(self) -> str:
    """Return MinIO endpoint with protocol."""
    protocol = "https" if self.minio_secure else "http"
    return f"{protocol}://{self.minio_endpoint}"
```

### Phase 2: Create MinIO Service

#### Step 2.1: Create app/services/minio_service.py

```python
"""
MinIO storage service for video files.

Provides S3-compatible object storage operations with:
- File upload/download
- Pre-signed URL generation
- Automatic bucket initialization
- Error handling and retries
"""

import io
from typing import BinaryIO, Union

from minio import Minio
from minio.error import S3Error
from app.config import settings
from app.core.exceptions import StorageError, StorageUnavailableError


class MinIOService:
    """Service for MinIO object storage operations."""
    
    _instance = None
    _client = None
    
    def __new__(cls):
        """Singleton pattern for MinIO client."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize MinIO client if not already initialized."""
        if self._client is None:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region=settings.minio_region
            )
            self._bucket_name = settings.minio_bucket_name
            self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist."""
        try:
            if not self._client.bucket_exists(self._bucket_name):
                self._client.make_bucket(self._bucket_name)
        except S3Error as e:
            raise StorageUnavailableError(
                f"Failed to initialize MinIO bucket: {e}"
            )
    
    async def upload_file(
        self,
        file_data: Union[bytes, BinaryIO],
        object_name: str,
        content_type: str = "video/mp4",
        metadata: dict = None
    ) -> str:
        """
        Upload file to MinIO.
        
        Args:
            file_data: File content as bytes or file-like object
            object_name: Target object path in bucket
            content_type: MIME type of the file
            metadata: Optional metadata dict
            
        Returns:
            The object_name that was stored
            
        Raises:
            StorageError: If upload fails
            StorageUnavailableError: If MinIO is unavailable
        """
        try:
            # Convert bytes to BytesIO if needed
            if isinstance(file_data, bytes):
                file_data = io.BytesIO(file_data)
            
            # Get file size
            file_data.seek(0, 2)  # Seek to end
            file_size = file_data.tell()
            file_data.seek(0)  # Reset to beginning
            
            self._client.put_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
                data=file_data,
                length=file_size,
                content_type=content_type,
                metadata=metadata or {}
            )
            
            return object_name
            
        except S3Error as e:
            raise StorageError(
                f"Failed to upload file to {object_name}: {e}"
            )
    
    async def download_file(self, object_name: str) -> bytes:
        """
        Download file from MinIO as bytes.
        
        Args:
            object_name: Object path in bucket
            
        Returns:
            File content as bytes
            
        Raises:
            StorageError: If download fails
        """
        try:
            response = self._client.get_object(
                bucket_name=self._bucket_name,
                object_name=object_name
            )
            return response.read()
            
        except S3Error as e:
            raise StorageError(
                f"Failed to download file {object_name}: {e}"
            )
    
    async def generate_presigned_url(
        self,
        object_name: str,
        expiry: int = None
    ) -> str:
        """
        Generate pre-signed URL for direct access.
        
        Args:
            object_name: Object path in bucket
            expiry: URL expiry time in seconds (default: 3600)
            
        Returns:
            Pre-signed URL string
            
        Raises:
            StorageError: If URL generation fails
        """
        if expiry is None:
            expiry = settings.minio_presigned_url_expiry
            
        try:
            url = self._client.presigned_get_object(
                bucket_name=self._bucket_name,
                object_name=object_name,
                expires=expiry
            )
            return url
            
        except S3Error as e:
            raise StorageError(
                f"Failed to generate presigned URL for {object_name}: {e}"
            )
    
    async def get_segment_url(
        self,
        job_id: str,
        segment_index: int,
        stage: str = "final",
        expiry: int = None
    ) -> str:
        """
        Get pre-signed URL for a specific video segment.
        
        Args:
            job_id: UUID of the job
            segment_index: Index of the segment
            stage: "stage1" for initial crop, "final" for JBI cropped
            expiry: URL expiry time in seconds
            
        Returns:
            Pre-signed URL string
        """
        if stage == "stage1":
            object_name = f"jobs/{job_id}/stage1/segment_{segment_index}.mp4"
        else:
            object_name = f"jobs/{job_id}/segments/{segment_index}.mp4"
            
        return await self.generate_presigned_url(object_name, expiry)
    
    async def delete_object(self, object_name: str) -> None:
        """
        Delete object from MinIO.
        
        Args:
            object_name: Object path in bucket
            
        Raises:
            StorageError: If deletion fails
        """
        try:
            self._client.remove_object(
                bucket_name=self._bucket_name,
                object_name=object_name
            )
        except S3Error as e:
            raise StorageError(
                f"Failed to delete object {object_name}: {e}"
            )
    
    async def object_exists(self, object_name: str) -> bool:
        """
        Check if object exists in bucket.
        
        Args:
            object_name: Object path in bucket
            
        Returns:
            True if object exists, False otherwise
        """
        try:
            self._client.stat_object(
                bucket_name=self._bucket_name,
                object_name=object_name
            )
            return True
        except S3Error:
            return False
    
    async def get_object_size(self, object_name: str) -> int:
        """
        Get object size in bytes.
        
        Args:
            object_name: Object path in bucket
            
        Returns:
            Size in bytes
            
        Raises:
            StorageError: If stat fails
        """
        try:
            stat = self._client.stat_object(
                bucket_name=self._bucket_name,
                object_name=object_name
            )
            return stat.size
        except S3Error as e:
            raise StorageError(
                f"Failed to get object stats for {object_name}: {e}"
            )
    
    async def upload_job_video(
        self,
        job_id: str,
        file_data: Union[bytes, BinaryIO],
        original_filename: str,
        content_type: str = "video/mp4"
    ) -> str:
        """
        Upload original video for a job.
        
        Args:
            job_id: UUID of the job
            file_data: Video file content
            original_filename: Original filename for reference
            content_type: MIME type
            
        Returns:
            Object name in MinIO
        """
        object_name = f"jobs/{job_id}/original/{original_filename}"
        await self.upload_file(
            file_data=file_data,
            object_name=object_name,
            content_type=content_type,
            metadata={"job_id": job_id, "type": "original"}
        )
        return object_name
    
    async def upload_segment(
        self,
        job_id: str,
        segment_index: int,
        file_data: Union[bytes, BinaryIO],
        stage: str = "final"
    ) -> str:
        """
        Upload a video segment.
        
        Args:
            job_id: UUID of the job
            segment_index: Index of the segment
            file_data: Video segment content
            stage: "stage1" or "final"
            
        Returns:
            Object name in MinIO
        """
        if stage == "stage1":
            object_name = f"jobs/{job_id}/stage1/segment_{segment_index}.mp4"
        else:
            object_name = f"jobs/{job_id}/segments/{segment_index}.mp4"
            
        await self.upload_file(
            file_data=file_data,
            object_name=object_name,
            content_type="video/mp4",
            metadata={
                "job_id": job_id,
                "segment_index": str(segment_index),
                "stage": stage
            }
        )
        return object_name


# Global service instance
minio_service = MinIOService()
```

### Phase 3: Add Storage Exceptions

#### Step 3.1: Update app/core/exceptions.py

```python
"""Custom application exceptions."""


class AppException(Exception):
    """Base application exception."""
    
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


# Authentication exceptions
class AuthenticationError(AppException):
    """Authentication failed."""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class AuthorizationError(AppException):
    """Authorization failed - insufficient permissions."""
    
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, status_code=403)


class TokenExpiredError(AuthenticationError):
    """JWT token has expired."""
    
    def __init__(self, message: str = "Token has expired"):
        super().__init__(message)


class TokenInvalidError(AuthenticationError):
    """JWT token is invalid."""
    
    def __init__(self, message: str = "Token is invalid"):
        super().__init__(message)


# Validation exceptions
class ValidationError(AppException):
    """Input validation failed."""
    
    def __init__(self, message: str = "Validation error", details: dict = None):
        self.details = details or {}
        super().__init__(message, status_code=400)


class ResourceNotFoundError(AppException):
    """Requested resource not found."""
    
    def __init__(self, resource_type: str = "Resource", resource_id: str = None):
        message = f"{resource_type} not found"
        if resource_id:
            message += f": {resource_id}"
        super().__init__(message, status_code=404)


# Storage exceptions (NEW)
class StorageError(AppException):
    """Storage operation failed."""
    
    def __init__(self, message: str = "Storage operation failed"):
        super().__init__(message, status_code=500)


class StorageUnavailableError(StorageError):
    """Storage service is unavailable."""
    
    def __init__(self, message: str = "Storage service is unavailable"):
        super().__init__(message)


# Job processing exceptions
class JobNotFoundError(ResourceNotFoundError):
    """Job not found."""
    
    def __init__(self, job_id: str = None):
        super().__init__("Job", job_id)


class JobProcessingError(AppException):
    """Job processing failed."""
    
    def __init__(self, message: str = "Job processing failed"):
        super().__init__(message, status_code=500)


class JobCancelledError(AppException):
    """Job was cancelled."""
    
    def __init__(self, message: str = "Job was cancelled"):
        super().__init__(message, status_code=409)
```

### Phase 4: Add MinIO to Docker Compose

#### Step 4.1: Update docker-compose.yml

```yaml
# Add to services section:

  # ── MinIO Object Storage ─────────────────────────────────
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"  # API port
      - "9001:9001"  # Console port
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

# Add to volumes section:
volumes:
  pgdata:
  uploads_data:
  outputs_data:
  minio_data:  # NEW
```

### Phase 5: Create API Endpoints

#### Step 5.1: Create app/api/v1/storage.py

```python
"""
Storage API endpoints for pre-signed URL generation.

These endpoints provide secure access to MinIO-stored videos
via time-limited pre-signed URLs.
"""

from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user
from app.db.models.auth import User
from app.services.minio_service import minio_service
from app.core.exceptions import StorageError, ResourceNotFoundError

router = APIRouter()


@router.get("/segments/{segment_id}/download-url")
async def get_segment_download_url(
    segment_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Generate pre-signed URL for segment download.
    
    Returns a time-limited URL that allows direct download
    from MinIO without API authentication.
    """
    try:
        # TODO: Verify user has access to this segment
        # This will be implemented when segment model is available
        
        # For now, construct object name from segment_id
        # In production, lookup segment in database to get path
        object_name = f"segments/{segment_id}.mp4"
        
        url = await minio_service.generate_presigned_url(object_name)
        
        return {
            "url": url,
            "expires_in_seconds": 3600,
            "segment_id": segment_id
        }
        
    except StorageError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/video-url")
async def get_job_video_url(
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Generate pre-signed URL for original job video.
    """
    try:
        # TODO: Verify user has access to this job
        # Lookup job to get original filename
        
        object_name = f"jobs/{job_id}/original/video.mp4"
        
        if not await minio_service.object_exists(object_name):
            raise ResourceNotFoundError("Video", job_id)
        
        url = await minio_service.generate_presigned_url(object_name)
        
        return {
            "url": url,
            "expires_in_seconds": 3600,
            "job_id": job_id
        }
        
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Phase 6: Testing

#### Step 6.1: Create tests/unit/services/test_minio_service.py

```python
"""Tests for MinIO service."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from minio.error import S3Error

from app.services.minio_service import MinIOService
from app.core.exceptions import StorageError, StorageUnavailableError


class TestMinIOService:
    """Test suite for MinIO service."""
    
    @pytest.fixture
    def mock_minio_client(self):
        """Mock MinIO client."""
        with patch('app.services.minio_service.Minio') as mock:
            client = Mock()
            mock.return_value = client
            # Reset singleton
            MinIOService._instance = None
            MinIOService._client = None
            yield client
    
    @pytest.fixture
    def minio_service(self, mock_minio_client):
        """Create MinIO service with mocked client."""
        mock_minio_client.bucket_exists.return_value = True
        return MinIOService()
    
    @pytest.mark.asyncio
    async def test_upload_file_success(self, minio_service, mock_minio_client):
        """Test successful file upload."""
        # Arrange
        file_data = b"test video content"
        object_name = "jobs/test/video.mp4"
        
        # Act
        result = await minio_service.upload_file(file_data, object_name)
        
        # Assert
        assert result == object_name
        mock_minio_client.put_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_upload_file_failure(self, minio_service, mock_minio_client):
        """Test file upload failure."""
        # Arrange
        mock_minio_client.put_object.side_effect = S3Error(
            "Mock error", "InternalError", None, None, None, None
        )
        
        # Act & Assert
        with pytest.raises(StorageError):
            await minio_service.upload_file(b"data", "test.mp4")
    
    @pytest.mark.asyncio
    async def test_generate_presigned_url(self, minio_service, mock_minio_client):
        """Test pre-signed URL generation."""
        # Arrange
        mock_minio_client.presigned_get_object.return_value = "http://minio/test-url"
        
        # Act
        url = await minio_service.generate_presigned_url("test.mp4")
        
        # Assert
        assert url == "http://minio/test-url"
        mock_minio_client.presigned_get_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_object_exists_true(self, minio_service, mock_minio_client):
        """Test object exists check - True case."""
        # Arrange
        mock_minio_client.stat_object.return_value = Mock(size=1024)
        
        # Act
        exists = await minio_service.object_exists("test.mp4")
        
        # Assert
        assert exists is True
    
    @pytest.mark.asyncio
    async def test_object_exists_false(self, minio_service, mock_minio_client):
        """Test object exists check - False case."""
        # Arrange
        mock_minio_client.stat_object.side_effect = S3Error(
            "Not found", "NoSuchKey", None, None, None, None
        )
        
        # Act
        exists = await minio_service.object_exists("test.mp4")
        
        # Assert
        assert exists is False
    
    @pytest.mark.asyncio
    async def test_upload_job_video(self, minio_service, mock_minio_client):
        """Test uploading job video."""
        # Arrange
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        file_data = b"video content"
        filename = "news.mp4"
        
        # Act
        result = await minio_service.upload_job_video(
            job_id, file_data, filename
        )
        
        # Assert
        expected_path = f"jobs/{job_id}/original/{filename}"
        assert result == expected_path
        mock_minio_client.put_object.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_upload_segment(self, minio_service, mock_minio_client):
        """Test uploading segment."""
        # Arrange
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        file_data = b"segment content"
        
        # Act - stage1
        result = await minio_service.upload_segment(
            job_id, 0, file_data, stage="stage1"
        )
        
        # Assert
        assert f"jobs/{job_id}/stage1/segment_0.mp4" == result
        
        # Act - final
        result = await minio_service.upload_segment(
            job_id, 1, file_data, stage="final"
        )
        
        # Assert
        assert f"jobs/{job_id}/segments/1.mp4" == result
```

#### Step 6.2: Create tests/integration/test_minio_integration.py

```python
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
        import asyncio
        await service.delete_object(f"jobs/{job_id}/original/original.mp4")
```

---

## Implementation Checklist

### Phase 1: Configuration
- [ ] Add MinIO settings to app/config.py
- [ ] Add minio to requirements.txt
- [ ] Update .env.example with MinIO variables

### Phase 2: Service Implementation
- [ ] Create app/services/minio_service.py
- [ ] Implement upload_file method
- [ ] Implement download_file method
- [ ] Implement generate_presigned_url method
- [ ] Implement helper methods (upload_job_video, upload_segment)

### Phase 3: Infrastructure
- [ ] Add MinIO service to docker-compose.yml
- [ ] Update .env with MinIO configuration

### Phase 4: Error Handling
- [ ] Add StorageError and StorageUnavailableError exceptions
- [ ] Ensure proper error messages in all service methods

### Phase 5: API Endpoints (Optional for this story)
- [ ] Create storage router
- [ ] Implement segment download URL endpoint
- [ ] Implement job video URL endpoint

### Phase 6: Testing
- [ ] Create unit tests with mocked MinIO
- [ ] Create integration tests (require running MinIO)
- [ ] Test upload/download/delete workflow

### Phase 7: Validation
- [ ] Run unit tests: `pytest tests/unit/services/test_minio_service.py -v`
- [ ] Run integration tests: `pytest tests/integration/test_minio_integration.py -v --integration`
- [ ] Verify MinIO console accessible at http://localhost:9001
- [ ] Test file upload via service

---

## Dependencies

**This story depends on:**
- Story 2.1: Database Schema - Pipeline Domain ✅

**Stories that depend on this:**
- Story 2.3: Video Upload API
- Story 2.4: PostgreSQL Queue Implementation
- Story 2.5: Detection Worker - YOLOv8
- Story 2.6: ASR Worker - faster-whisper
- Story 2.7: Cropping Worker - JBI Buffer
- Story 2.8: Job Status API & Polling
- Story 2.9: Job Cancellation
- Story 2.10: Health Check & System Monitoring

---

## Next Story

After completing this story, proceed to:  
**Story 2.3: Video Upload API**

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. MinIO is a **foundation component** - all subsequent Epic 2 stories depend on it
2. Always use pre-signed URLs for client access (security requirement)
3. Object naming convention is critical for later stories
4. Handle MinIO unavailability gracefully (retry logic in workers)

**Object Naming Convention:**
```
jobs/{job_id}/original/{filename}    # Original upload
jobs/{job_id}/stage1/segment_{n}.mp4 # Stage 1 cropped
jobs/{job_id}/segments/{n}.mp4       # Final JBI cropped
```

**Common Mistakes to Avoid:**
- ❌ Storing files on local filesystem instead of MinIO
- ❌ Using API to proxy video downloads (use pre-signed URLs!)
- ❌ Hardcoding bucket names (use config)
- ❌ Forgetting to handle S3Error exceptions

**Performance Considerations:**
- MinIO client is a singleton (connection reuse)
- Pre-signed URLs offload streaming from API server
- Use streaming uploads for large files
- Configure appropriate part sizes for multipart uploads

**Security Considerations:**
- Pre-signed URLs expire after 1 hour (NFR10)
- MinIO credentials in environment variables
- Bucket policies restrict public access
- Console port (9001) should not be exposed in production

---

## Dev Agent Record

### Implementation Plan
- **Approach**: Create MinIO service singleton, implement CRUD operations, add Docker service
- **Key Decisions**:
  - Singleton pattern for MinIO client (connection reuse)
  - Async methods for consistency with FastAPI
  - Separate methods for job videos vs segments
  - Automatic bucket creation on startup

### Files to Create/Modify
| File | Action | Description |
|------|--------|-------------|
| `app/config.py` | Modify | Add MinIO configuration settings |
| `app/services/minio_service.py` | Create | MinIO operations service |
| `app/core/exceptions.py` | Modify | Add StorageError exceptions |
| `docker-compose.yml` | Modify | Add MinIO service |
| `.env.example` | Modify | Add MinIO env vars |
| `requirements.txt` | Modify | Add minio-py dependency |
| `app/api/v1/storage.py` | Create | (Optional) Pre-signed URL endpoints |
| `tests/unit/services/test_minio_service.py` | Create | Unit tests |
| `tests/integration/test_minio_integration.py` | Create | Integration tests |

### External Dependencies
- **minio-py**: MinIO Python client library
- **Docker**: MinIO runs as containerized service

### Configuration Summary
```bash
# Environment variables to add to .env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=anotasi-videos
MINIO_SECURE=false
MINIO_PRESIGNED_URL_EXPIRY=3600
```

### Service Methods Summary
| Method | Purpose | Async |
|--------|---------|-------|
| `upload_file` | Upload bytes/file to MinIO | ✅ |
| `download_file` | Download object as bytes | ✅ |
| `generate_presigned_url` | Create time-limited access URL | ✅ |
| `get_segment_url` | Get URL for specific segment | ✅ |
| `delete_object` | Remove object from bucket | ✅ |
| `object_exists` | Check object existence | ✅ |
| `get_object_size` | Get object size in bytes | ✅ |
| `upload_job_video` | Upload original job video | ✅ |
| `upload_segment` | Upload processed segment | ✅ |

### Testing Strategy
1. **Unit Tests**: Mock MinIO client, test all methods
2. **Integration Tests**: Requires running MinIO container
3. **Manual Testing**: Upload file, verify in MinIO console
