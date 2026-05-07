"""
Tus Protocol upload service for chunked file uploads.

Handles:
- Upload initialization and tracking
- Chunk storage in MinIO temp bucket
- Parallel chunk handling
- File assembly and verification
- Cleanup of temporary chunks
"""

import base64
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from uuid import UUID, uuid4

from minio import Minio
from minio.commonconfig import ComposeSource
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import StorageError, NotFoundError, ValidationError
from app.db.models import Upload, PipelineJob, QueueJob, JobStatus, User
from app.schemas.job import SignLanguageCategory

logger = logging.getLogger(__name__)


class UploadService:
    """Service for handling Tus Protocol chunked uploads."""
    
    # Constants
    DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
    TEMP_BUCKET = "temp-uploads"
    FINAL_BUCKET = settings.minio_bucket_name
    UPLOAD_EXPIRY_HOURS = 24
    
    def __init__(self, db: AsyncSession, minio_client: Optional[Minio] = None):
        """
        Initialize upload service.
        
        Args:
            db: Database session (async)
            minio_client: Optional MinIO client (creates new if not provided)
        """
        self.db = db
        if minio_client is None:
            self.minio = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region=settings.minio_region
            )
        else:
            self.minio = minio_client
        
        self._ensure_buckets_exist()
    
    def _ensure_buckets_exist(self) -> None:
        """Create required buckets if they don't exist."""
        for bucket in [self.TEMP_BUCKET, self.FINAL_BUCKET]:
            try:
                if not self.minio.bucket_exists(bucket):
                    self.minio.make_bucket(bucket)
                    logger.info(f"Created bucket: {bucket}")
            except S3Error as e:
                if "BucketAlreadyExists" not in str(e):
                    logger.error(f"Failed to create bucket {bucket}: {e}")
                    raise StorageError(f"Failed to initialize bucket {bucket}")
    
    def parse_tus_metadata(self, metadata_header: Optional[str]) -> dict:
        """
        Parse Tus Upload-Metadata header.
        
        Format: key1 base64(value1),key2 base64(value2)
        """
        if not metadata_header:
            return {}
        
        result = {}
        pairs = metadata_header.split(",")
        
        for pair in pairs:
            pair = pair.strip()
            if not pair:
                continue
            
            if " " in pair:
                key, encoded_value = pair.split(" ", 1)
                try:
                    value = base64.b64decode(encoded_value).decode("utf-8")
                    result[key] = value
                except Exception:
                    result[key] = encoded_value
            else:
                result[pair] = ""
        
        return result
    
    async def create_upload(
        self,
        user: User,
        file_size: int,
        metadata: Optional[str] = None
    ) -> Upload:
        """
        Create a new upload resource.
        
        Args:
            user: Uploading user
            file_size: Total file size in bytes
            metadata: Tus metadata header value
            
        Returns:
            Created Upload record
        """
        # Validate file size
        if file_size > self.MAX_FILE_SIZE:
            raise ValidationError(
                f"File too large. Maximum size: {self.MAX_FILE_SIZE} bytes (10GB)"
            )
        
        if file_size <= 0:
            raise ValidationError("File size must be greater than 0")
        
        # Parse metadata
        parsed_metadata = self.parse_tus_metadata(metadata)
        
        # Validate category if provided
        category = parsed_metadata.get("category")
        if category is not None:
            try:
                # Validate using enum
                SignLanguageCategory(category)
            except ValueError:
                valid_values = [c.value for c in SignLanguageCategory]
                raise ValidationError(
                    f"Invalid category '{category}'. Must be one of: {', '.join(valid_values)}"
                )
        
        # Calculate chunks
        total_chunks = (file_size + self.DEFAULT_CHUNK_SIZE - 1) // self.DEFAULT_CHUNK_SIZE
        
        # Generate upload ID
        upload_id = str(uuid4())
        
        # Create temp storage prefix
        temp_prefix = f"uploads/{user.id}/{upload_id}/"
        
        # Create upload record
        upload = Upload(
            upload_id=upload_id,
            filename=parsed_metadata.get("filename", "unknown"),
            file_size=file_size,
            mime_type=parsed_metadata.get("filetype"),
            chunk_size=self.DEFAULT_CHUNK_SIZE,
            total_chunks=total_chunks,
            chunks_received=[],
            chunks_uploading=[],
            temp_bucket=self.TEMP_BUCKET,
            temp_prefix=temp_prefix,
            final_bucket=self.FINAL_BUCKET,
            final_key=None,
            category=category,
            user_id=user.id,
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=self.UPLOAD_EXPIRY_HOURS),
        )
        
        self.db.add(upload)
        await self.db.flush()
        await self.db.refresh(upload)
        
        logger.info(
            f"Created upload {upload_id} for user {user.id}: "
            f"{upload.filename} ({file_size} bytes, {total_chunks} chunks)"
        )
        
        return upload
    
    async def get_upload(self, upload_id: str, user_id: UUID) -> Upload:
        """
        Get upload by ID, verifying user ownership.
        
        Args:
            upload_id: Tus upload ID
            user_id: User ID for verification
            
        Returns:
            Upload record
            
        Raises:
            NotFoundError: If upload not found or not owned by user
        """
        result = await self.db.execute(
            select(Upload).where(
                Upload.upload_id == upload_id,
                Upload.user_id == user_id
            )
        )
        upload = result.scalar_one_or_none()
        
        if not upload:
            raise NotFoundError(f"Upload {upload_id} not found")
        
        return upload
    
    async def get_upload_offset(self, upload_id: str, user_id: UUID) -> int:
        """
        Get current upload offset for resume.
        
        Args:
            upload_id: Tus upload ID
            user_id: User ID
            
        Returns:
            Number of bytes received so far
        """
        upload = await self.get_upload(upload_id, user_id)
        
        # Calculate offset from received chunks
        if upload.status == "complete":
            return upload.file_size
        
        # Count complete chunks
        received_count = len(upload.chunks_received)
        offset = received_count * upload.chunk_size
        
        # Handle partial last chunk (shouldn't happen with Tus but be safe)
        if offset > upload.file_size:
            offset = upload.file_size
        
        return offset
    
    async def store_chunk(
        self,
        upload_id: str,
        user_id: UUID,
        chunk_data: bytes,
        offset: int
    ) -> int:
        """
        Store an upload chunk.
        
        Supports parallel uploads - chunks can arrive in any order.
        
        Args:
            upload_id: Tus upload ID
            user_id: User ID
            chunk_data: Raw chunk bytes
            offset: Byte offset for this chunk
            
        Returns:
            New offset after storing this chunk
            
        Raises:
            NotFoundError: If upload not found
            ValidationError: If chunk is invalid
        """
        upload = await self.get_upload(upload_id, user_id)
        
        # Validate offset aligns with chunk boundaries
        chunk_index = offset // upload.chunk_size
        expected_offset = chunk_index * upload.chunk_size
        
        if offset != expected_offset:
            raise ValidationError(
                f"Invalid offset {offset}. Expected {expected_offset} for chunk {chunk_index}"
            )
        
        if chunk_index >= upload.total_chunks:
            raise ValidationError(f"Chunk index {chunk_index} exceeds total chunks")
        
        # Check if already received
        if chunk_index in upload.chunks_received:
            logger.debug(f"Chunk {chunk_index} already received for upload {upload_id}")
            return offset + len(chunk_data)
        
        # Store chunk in MinIO temp bucket
        chunk_key = f"{upload.temp_prefix}chunk_{chunk_index:08d}"
        
        try:
            self.minio.put_object(
                bucket_name=upload.temp_bucket,
                object_name=chunk_key,
                data=io.BytesIO(chunk_data),
                length=len(chunk_data),
            )
            
            # Update upload record
            chunks_received = list(upload.chunks_received)
            chunks_received.append(chunk_index)
            chunks_received.sort()
            upload.chunks_received = chunks_received
            
            upload.status = "uploading"
            upload.updated_at = datetime.utcnow()
            
            # Check if all chunks received
            if len(upload.chunks_received) == upload.total_chunks:
                upload.status = "assembling"
                logger.info(f"All chunks received for upload {upload_id}, starting assembly")
            
            await self.db.flush()
            
            new_offset = offset + len(chunk_data)
            logger.debug(
                f"Stored chunk {chunk_index} for upload {upload_id}: "
                f"{len(chunk_data)} bytes, progress {len(upload.chunks_received)}/{upload.total_chunks}"
            )
            
            return new_offset
            
        except S3Error as e:
            logger.error(f"Failed to store chunk {chunk_index} for upload {upload_id}: {e}")
            raise StorageError(f"Failed to store chunk: {e}")
    
    async def assemble_file(self, upload: Upload) -> str:
        """
        Assemble all chunks into final file.
        
        Args:
            upload: Upload record with all chunks received
            
        Returns:
            Final object key in MinIO
        """
        if len(upload.chunks_received) != upload.total_chunks:
            raise ValidationError(
                f"Cannot assemble: missing chunks. "
                f"Received {len(upload.chunks_received)}/{upload.total_chunks}"
            )
        
        logger.info(f"Assembling upload {upload.upload_id}: {upload.total_chunks} chunks")
        
        # Build list of sources for MinIO compose
        sources = [
            ComposeSource(
                upload.temp_bucket,
                f"{upload.temp_prefix}chunk_{i:08d}"
            )
            for i in range(upload.total_chunks)
        ]
        
        # Generate final key using job_id pattern for assets.py router compatibility
        if not upload.job_id:
            upload.job_id = uuid4()
            
        # Basic sanitization for filename
        import os
        import re
        basename = os.path.basename(upload.filename)
        safe_filename = re.sub(r'[^\w\s\-\.\[\]]', '_', basename)
        if not safe_filename:
            safe_filename = "video.mp4"
            
        final_key = f"jobs/{upload.job_id}/original/{safe_filename}"
        
        try:
            # Compose chunks into final file
            self.minio.compose_object(
                bucket_name=upload.final_bucket,
                object_name=final_key,
                sources=sources,
            )
            
            # Verify file size
            stat = self.minio.stat_object(upload.final_bucket, final_key)
            if stat.size != upload.file_size:
                # Delete corrupted file
                self.minio.remove_object(upload.final_bucket, final_key)
                raise StorageError(
                    f"Size mismatch after assembly: {stat.size} != {upload.file_size}"
                )
            
            logger.info(
                f"Successfully assembled upload {upload.upload_id}: "
                f"{final_key} ({stat.size} bytes)"
            )
            
            return final_key
            
        except S3Error as e:
            logger.error(f"Failed to assemble upload {upload.upload_id}: {e}")
            raise StorageError(f"Failed to assemble file: {e}")
    
    async def cancel_upload(self, upload_id: str, user_id: UUID) -> None:
        """
        Cancel upload and cleanup temporary chunks.
        
        Args:
            upload_id: Tus upload ID
            user_id: User ID
        """
        upload = await self.get_upload(upload_id, user_id)
        
        # Cleanup temp chunks
        await self._cleanup_temp_chunks(upload)
        
        # Mark as cancelled
        upload.status = "cancelled"
        await self.db.flush()
        
        logger.info(f"Cancelled upload {upload_id}")
    
    async def _cleanup_temp_chunks(self, upload: Upload) -> None:
        """Delete temporary chunk files from MinIO."""
        for i in range(upload.total_chunks):
            chunk_key = f"{upload.temp_prefix}chunk_{i:08d}"
            try:
                self.minio.remove_object(upload.temp_bucket, chunk_key)
            except S3Error as e:
                logger.warning(f"Failed to delete chunk {chunk_key}: {e}")
    
    async def cleanup_stale_uploads(self, max_age_hours: int = 24) -> int:
        """
        Cleanup incomplete uploads older than specified hours.
        
        Args:
            max_age_hours: Maximum age for incomplete uploads
            
        Returns:
            Number of uploads cleaned up
        """
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        result = await self.db.execute(
            select(Upload).where(
                Upload.status.in_(["pending", "uploading", "assembling"]),
                Upload.expires_at < cutoff,
            )
        )
        stale_uploads = result.scalars().all()
        
        count = 0
        for upload in stale_uploads:
            try:
                await self._cleanup_temp_chunks(upload)
                upload.status = "cancelled"
                count += 1
            except Exception as e:
                logger.error(f"Failed to cleanup upload {upload.upload_id}: {e}")
        
        await self.db.flush()
        
        if count > 0:
            logger.info(f"Cleaned up {count} stale uploads")
        
        return count
