"""
MinIO storage service for video files.

Provides S3-compatible object storage operations with:
- File upload/download
- Pre-signed URL generation
- Automatic bucket initialization
- Error handling and retries
"""

import asyncio
import io
import os
import threading
from typing import BinaryIO, Union

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import MaxRetryError

from app.core.config import settings
from app.core.exceptions import StorageError, StorageUnavailableError


class MinIOService:
    """Service for MinIO object storage operations."""
    
    _instance = None
    _client = None
    _initialized = False
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern for MinIO client."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize MinIO client if not already initialized."""
        if self._initialized:
            return
            
        with self._lock:
            # Double-check after acquiring lock
            if self._initialized:
                return
                
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
    
    @property
    def client(self):
        """Access the MinIO client."""
        return self._client
    
    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist."""
        try:
            if not self._client.bucket_exists(self._bucket_name):
                try:
                    self._client.make_bucket(self._bucket_name)
                except S3Error as e:
                    # Bucket might have been created by another instance (TOCTOU)
                    if "BucketAlreadyExists" not in str(e):
                        raise
        except (S3Error, MaxRetryError) as e:
            raise StorageUnavailableError(
                f"Failed to initialize MinIO bucket: {e}"
            )
    
    def _upload_file_sync(
        self,
        file_data: Union[bytes, BinaryIO],
        object_name: str,
        content_type: str,
        metadata: dict
    ) -> str:
        """Synchronous upload implementation."""
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
            return await asyncio.to_thread(
                self._upload_file_sync,
                file_data,
                object_name,
                content_type,
                metadata
            )
        except (S3Error, MaxRetryError) as e:
            raise StorageError(
                f"Failed to upload file to {object_name}: {e}"
            )
    
    def _download_file_sync(self, object_name: str) -> bytes:
        """Synchronous download implementation with proper resource cleanup."""
        with self._client.get_object(
            bucket_name=self._bucket_name,
            object_name=object_name
        ) as response:
            return response.read()
    
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
            return await asyncio.to_thread(
                self._download_file_sync,
                object_name
            )
        except (S3Error, MaxRetryError) as e:
            raise StorageError(
                f"Failed to download file {object_name}: {e}"
            )
    
    def _generate_presigned_url_sync(
        self,
        object_name: str,
        expiry: int
    ) -> str:
        """Synchronous presigned URL generation."""
        from datetime import timedelta
        return self._client.presigned_get_object(
            bucket_name=self._bucket_name,
            object_name=object_name,
            expires=timedelta(seconds=expiry)
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
            return await asyncio.to_thread(
                self._generate_presigned_url_sync,
                object_name,
                expiry
            )
        except (S3Error, MaxRetryError) as e:
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
    
    def _delete_object_sync(self, object_name: str) -> None:
        """Synchronous delete implementation."""
        self._client.remove_object(
            bucket_name=self._bucket_name,
            object_name=object_name
        )
    
    async def delete_object(self, object_name: str) -> None:
        """
        Delete object from MinIO.
        
        Args:
            object_name: Object path in bucket
            
        Raises:
            StorageError: If deletion fails
        """
        try:
            await asyncio.to_thread(
                self._delete_object_sync,
                object_name
            )
        except (S3Error, MaxRetryError) as e:
            raise StorageError(
                f"Failed to delete object {object_name}: {e}"
            )
            
    def _delete_objects_by_prefix_sync(self, prefix: str) -> int:
        """Synchronous bulk delete implementation."""
        from minio.deleteobjects import DeleteObject
        
        objects_to_delete = self._client.list_objects(
            bucket_name=self._bucket_name,
            prefix=prefix,
            recursive=True
        )
        
        delete_object_list = [DeleteObject(obj.object_name) for obj in objects_to_delete]
        
        if not delete_object_list:
            return 0
            
        errors = self._client.remove_objects(
            bucket_name=self._bucket_name,
            delete_object_list=delete_object_list
        )
        
        error_count = 0
        for error in errors:
            error_count += 1
            import logging
            logging.getLogger(__name__).error(f"Error deleting object {error.object_name}: {error.message}")
            
        return len(delete_object_list) - error_count

    async def delete_objects_by_prefix(self, prefix: str) -> int:
        """
        Delete all objects matching a prefix from MinIO.
        
        Args:
            prefix: Prefix to match objects against
            
        Returns:
            Number of objects successfully deleted
            
        Raises:
            StorageError: If deletion fails
        """
        try:
            return await asyncio.to_thread(
                self._delete_objects_by_prefix_sync,
                prefix
            )
        except (S3Error, MaxRetryError) as e:
            raise StorageError(
                f"Failed to delete objects with prefix {prefix}: {e}"
            )
    
    def _object_exists_sync(self, object_name: str) -> bool:
        """Synchronous exists check - only returns False for NoSuchKey."""
        try:
            self._client.stat_object(
                bucket_name=self._bucket_name,
                object_name=object_name
            )
            return True
        except S3Error as e:
            # Only return False for actual "not found" errors
            if "NoSuchKey" in str(e) or "Not found" in str(e):
                return False
            # Re-raise other errors (auth, network, etc.)
            raise
    
    async def object_exists(self, object_name: str) -> bool:
        """
        Check if object exists in bucket.
        
        Args:
            object_name: Object path in bucket
            
        Returns:
            True if object exists, False otherwise
            
        Raises:
            StorageError: For non-NotFound errors (auth, network, etc.)
        """
        try:
            return await asyncio.to_thread(
                self._object_exists_sync,
                object_name
            )
        except S3Error as e:
            # Re-raise as StorageError for non-NotFound errors
            raise StorageError(
                f"Failed to check object existence for {object_name}: {e}"
            )
        except MaxRetryError as e:
            raise StorageUnavailableError(
                f"MinIO unavailable while checking object {object_name}: {e}"
            )
    
    def _get_object_size_sync(self, object_name: str) -> int:
        """Synchronous size retrieval."""
        stat = self._client.stat_object(
            bucket_name=self._bucket_name,
            object_name=object_name
        )
        return stat.size
    
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
            return await asyncio.to_thread(
                self._get_object_size_sync,
                object_name
            )
        except (S3Error, MaxRetryError) as e:
            raise StorageError(
                f"Failed to get object stats for {object_name}: {e}"
            )
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to prevent path traversal attacks.
        
        Removes path components and keeps only the basename.
        """
        # Get basename (removes any path components)
        basename = os.path.basename(filename)
        
        # Remove any remaining problematic characters
        # Allow alphanumeric, dots, dashes, underscores
        sanitized = "".join(c for c in basename if c.isalnum() or c in "._-")
        
        # Ensure we have something left
        if not sanitized:
            raise ValueError(f"Invalid filename after sanitization: {filename}")
            
        return sanitized
    
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
            original_filename: Original filename for reference (will be sanitized)
            content_type: MIME type
            
        Returns:
            Object name in MinIO
            
        Raises:
            ValueError: If filename is invalid after sanitization
        """
        # Sanitize filename to prevent path traversal
        safe_filename = self._sanitize_filename(original_filename)
        
        object_name = f"jobs/{job_id}/original/{safe_filename}"
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
