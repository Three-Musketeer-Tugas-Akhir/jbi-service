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

from app.core.config import settings
from app.core.exceptions import StorageError, StorageUnavailableError


class MinIOService:
    """Service for MinIO object storage operations."""
    
    _instance = None
    _client = None
    _initialized = False
    
    def __new__(cls):
        """Singleton pattern for MinIO client."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize MinIO client if not already initialized."""
        if not self._initialized:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region=settings.minio_region
            )
            self._bucket_name = settings.minio_bucket_name
            self._ensure_bucket_exists()
            self._initialized = True
    
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


# Global service instance (lazy-loaded)
_minio_service_instance = None


def get_minio_service() -> MinIOService:
    """Get or create the MinIO service singleton."""
    global _minio_service_instance
    if _minio_service_instance is None:
        _minio_service_instance = MinIOService()
    return _minio_service_instance
