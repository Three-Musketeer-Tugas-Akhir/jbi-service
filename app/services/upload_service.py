"""
Tus Protocol upload service for chunked file uploads.

Handles:
- Upload initialization and tracking
- Chunk storage in MinIO temp bucket
- Parallel chunk handling with streaming I/O
- File assembly and verification
- Cleanup of temporary chunks

Performance optimisations:
- All MinIO calls run in asyncio thread pool (non-blocking)
- Chunk data streamed via temp files (no double-buffering in RAM)
- 50 MB default chunk size (fewer HTTP round-trips)
"""

import asyncio
import base64
import io
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from minio import Minio
from minio.commonconfig import ComposeSource
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.exceptions import StorageError, NotFoundError, ValidationError
from app.db.models import Upload, PipelineJob, QueueJob, JobStatus, User
from app.schemas.job import SignLanguageCategory

logger = logging.getLogger(__name__)


class UploadService:
    """Service for handling Tus Protocol chunked uploads."""
    
    # Constants
    # 4MB per chunk. The browser reaches this API through the frontend's proxy
    # rewrite, which rejects large request bodies with a 502
    # (ROUTER_EXTERNAL_TARGET_ERROR) — so a PATCH bigger than this never
    # arrives at all. Measured against the deployed proxy: 4MB succeeded on
    # every attempt, 6MB and 8MB were intermittent, and everything from 9MB up
    # failed outright. The previous 50MB meant every chunk of every local
    # upload 502'd, which is why local upload never worked while the
    # server-side YouTube path (no browser request body) did.
    #
    # Clients are told this value via the Upload-Chunk-Size response header on
    # create; do not hardcode it separately on the client.
    DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
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
        
        # Parse dataset_id if provided
        dataset_id_str = parsed_metadata.get("dataset_id")
        dataset_id = None
        if dataset_id_str:
            try:
                dataset_id = UUID(dataset_id_str)
            except ValueError:
                raise ValidationError(f"Invalid dataset_id '{dataset_id_str}'. Must be a valid UUID.")
        
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
            dataset_id=dataset_id,
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=self.UPLOAD_EXPIRY_HOURS),
        )
        
        self.db.add(upload)
        await self.db.flush()
        await self.db.refresh(upload)
        
        logger.info(
            f"Created upload {upload_id} for user {user.id}: "
            f"{upload.filename} ({file_size} bytes, {total_chunks} chunks of {self.DEFAULT_CHUNK_SIZE} bytes)"
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

    async def get_upload_locked(self, upload_id: str, user_id: UUID) -> Upload:
        """
        Get upload by ID with row-level locking (SELECT FOR UPDATE).
        
        Use this when updating chunks_received to prevent race conditions
        from parallel chunk uploads.
        
        Args:
            upload_id: Tus upload ID
            user_id: User ID for verification
            
        Returns:
            Upload record (locked)
            
        Raises:
            NotFoundError: If upload not found or not owned by user
        """
        result = await self.db.execute(
            select(Upload)
            .where(
                Upload.upload_id == upload_id,
                Upload.user_id == user_id
            )
            .with_for_update()
        )
        upload = result.scalar_one_or_none()
        
        if not upload:
            raise NotFoundError(f"Upload {upload_id} not found")
        
        return upload
    
    async def get_upload_offset(self, upload_id: str, user_id: UUID) -> int:
        """
        Get current upload offset for resume.
        
        Returns the byte offset of the first missing chunk,
        so resumable uploads work correctly.
        
        Args:
            upload_id: Tus upload ID
            user_id: User ID
            
        Returns:
            Number of bytes received so far (contiguous from start)
        """
        upload = await self.get_upload(upload_id, user_id)
        
        if upload.status == "complete":
            return upload.file_size
        
        # Count contiguous chunks from the start (0, 1, 2, ...)
        received = set(upload.chunks_received or [])
        contiguous_count = 0
        for i in range(upload.total_chunks):
            if i in received:
                contiguous_count += 1
            else:
                break
        
        # Calculate byte offset
        if contiguous_count == upload.total_chunks:
            return upload.file_size
        
        offset = contiguous_count * upload.chunk_size
        
        # Clamp to file_size
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
        Store an upload chunk (legacy in-memory path).
        
        Uses row-level locking to prevent race conditions from parallel uploads.
        
        For the streaming path see ``store_chunk_streaming``.
        """
        chunk_size = len(chunk_data)
        chunk_index: int | None = None

        try:
            # Run blocking MinIO put in thread pool → unblock event loop
            # Upload BEFORE acquiring lock to minimize lock duration
            # (orphaned chunks are cleaned up later)
            upload_temp = await self.get_upload(upload_id, user_id)
            chunk_index, _ = self._validate_chunk(upload_temp, offset, chunk_size)
            
            if chunk_index is None:
                # Already received — return next offset
                return offset + chunk_size

            chunk_key = f"{upload_temp.temp_prefix}chunk_{chunk_index:08d}"
            
            await asyncio.to_thread(
                self.minio.put_object,
                bucket_name=upload_temp.temp_bucket,
                object_name=chunk_key,
                data=io.BytesIO(chunk_data),
                length=chunk_size,
            )

            # Acquire lock and update DB atomically
            upload = await self.get_upload_locked(upload_id, user_id)
            
            # Re-validate after acquiring lock (might have been updated by another request)
            chunk_index, _ = self._validate_chunk(upload, offset, chunk_size)
            if chunk_index is None:
                logger.debug(f"Chunk at offset {offset} already received (race condition avoided)")
                return offset + chunk_size

            self._mark_chunk_received(upload, chunk_index)
            await self.db.flush()

            new_offset = offset + chunk_size
            logger.debug(
                f"Stored chunk {chunk_index} for upload {upload_id}: "
                f"{chunk_size} bytes, progress {len(upload.chunks_received)}/{upload.total_chunks}"
            )
            return new_offset

        except S3Error as e:
            logger.error(f"Failed to store chunk {chunk_index} for upload {upload_id}: {e}")
            raise StorageError(f"Failed to store chunk: {e}")

    async def store_chunk_streaming(
        self,
        upload_id: str,
        user_id: UUID,
        chunk_path: str,
        chunk_size: int,
        offset: int,
    ) -> int:
        """
        Store an upload chunk from a temp file (streaming path).

        This avoids loading the entire chunk into Python memory by
        reading directly from the file on disk.

        Uses row-level locking to prevent race conditions from parallel uploads.

        Args:
            upload_id: Tus upload ID
            user_id: User ID
            chunk_path: Path to temporary file containing chunk data
            chunk_size: Size of the chunk in bytes
            offset: Byte offset for this chunk

        Returns:
            New offset after storing this chunk
        """
        chunk_index: int | None = None

        try:
            # Step 1: Pre-validate without lock and upload to MinIO
            # Upload BEFORE acquiring lock to minimize lock duration
            # (orphaned chunks are cleaned up later)
            upload_temp = await self.get_upload(upload_id, user_id)
            chunk_index, _ = self._validate_chunk(upload_temp, offset, chunk_size)

            if chunk_index is None:
                return offset + chunk_size

            chunk_key = f"{upload_temp.temp_prefix}chunk_{chunk_index:08d}"

            # Upload from file handle in thread pool — zero RAM copy
            def _upload_from_file():
                with open(chunk_path, "rb") as fh:
                    self.minio.put_object(
                        bucket_name=upload_temp.temp_bucket,
                        object_name=chunk_key,
                        data=fh,
                        length=chunk_size,
                    )

            await asyncio.to_thread(_upload_from_file)

            # Step 2: Acquire lock and update DB atomically
            upload = await self.get_upload_locked(upload_id, user_id)

            # Re-validate after acquiring lock (might have been updated by another request)
            chunk_index, _ = self._validate_chunk(upload, offset, chunk_size)
            if chunk_index is None:
                logger.debug(f"Chunk at offset {offset} already received (race condition avoided)")
                return offset + chunk_size

            self._mark_chunk_received(upload, chunk_index)
            await self.db.flush()

            new_offset = offset + chunk_size
            logger.debug(
                f"Stored chunk (streaming) {chunk_index} for upload {upload_id}: "
                f"{chunk_size} bytes, progress {len(upload.chunks_received)}/{upload.total_chunks}"
            )
            return new_offset

        except S3Error as e:
            logger.error(f"Failed to store chunk {chunk_index} for upload {upload_id}: {e}")
            raise StorageError(f"Failed to store chunk: {e}")

    # ── Internal helpers ────────────────────────────────────────────

    def _validate_chunk(
        self, upload, offset: int, chunk_size: int,
    ) -> tuple:
        """
        Validate a chunk and return (chunk_index, is_complete).
        Returns (None, False) if the chunk was already received.
        """
        if upload.status in ("complete", "cancelled", "failed"):
            raise ValidationError(f"Upload {upload.upload_id} is already {upload.status}")

        chunk_index = offset // upload.chunk_size
        expected_offset = chunk_index * upload.chunk_size

        if offset != expected_offset:
            raise ValidationError(
                f"Invalid offset {offset}. Expected {expected_offset} for chunk {chunk_index}"
            )

        if chunk_index >= upload.total_chunks:
            raise ValidationError(
                f"Chunk index {chunk_index} exceeds total chunks {upload.total_chunks}"
            )

        # Size validation (warning only — don't reject)
        is_last_chunk = (chunk_index == upload.total_chunks - 1)
        if is_last_chunk:
            expected_size = upload.file_size - (chunk_index * upload.chunk_size)
            if chunk_size != expected_size:
                logger.warning(
                    f"Last chunk size mismatch for upload {upload.upload_id}: "
                    f"expected={expected_size}, actual={chunk_size}"
                )
        else:
            if chunk_size != upload.chunk_size:
                logger.warning(
                    f"Chunk {chunk_index} size mismatch for upload {upload.upload_id}: "
                    f"expected={upload.chunk_size}, actual={chunk_size}"
                )

        # Duplicate check
        current_received = list(upload.chunks_received or [])
        if chunk_index in current_received:
            logger.debug(
                f"Chunk {chunk_index} already received for upload {upload.upload_id}"
            )
            return None, False

        return chunk_index, False

    def _mark_chunk_received(self, upload, chunk_index: int) -> None:
        """Update the upload record after a chunk is stored."""
        current_received = list(upload.chunks_received or [])
        current_received.append(chunk_index)
        current_received.sort()
        upload.chunks_received = current_received
        flag_modified(upload, "chunks_received")

        upload.status = "uploading"
        upload.updated_at = datetime.utcnow()

        if len(upload.chunks_received) == upload.total_chunks:
            upload.status = "assembling"
            logger.info(
                f"All {upload.total_chunks} chunks received for upload "
                f"{upload.upload_id}, starting assembly"
            )
    
    async def assemble_file(self, upload: Upload) -> str:
        """
        Assemble all chunks into final file.
        
        All MinIO operations run in the thread pool to avoid blocking
        the async event loop during potentially long compose operations.
        """
        received_count = len(upload.chunks_received or [])
        if received_count != upload.total_chunks:
            raise ValidationError(
                f"Cannot assemble: missing chunks. "
                f"Received {received_count}/{upload.total_chunks}"
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
            
        import re as _re
        basename = os.path.basename(upload.filename)
        safe_filename = _re.sub(r'[^\w\s\-\.\[\]]', '_', basename)
        if not safe_filename:
            safe_filename = "video.mp4"
            
        final_key = f"jobs/{upload.job_id}/original/{safe_filename}"
        
        try:
            MAX_COMPOSE_SOURCES = 500
            
            if len(sources) <= MAX_COMPOSE_SOURCES:
                await asyncio.to_thread(
                    self.minio.compose_object,
                    bucket_name=upload.final_bucket,
                    object_name=final_key,
                    sources=sources,
                )
            else:
                final_key = await self._multi_stage_compose(
                    upload, sources, final_key, MAX_COMPOSE_SOURCES
                )
            
            # Verify file size (thread pool)
            stat = await asyncio.to_thread(
                self.minio.stat_object, upload.final_bucket, final_key
            )
            if stat.size != upload.file_size:
                await asyncio.to_thread(
                    self.minio.remove_object, upload.final_bucket, final_key
                )
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
    
    async def _multi_stage_compose(
        self,
        upload: Upload,
        sources: list,
        final_key: str,
        batch_size: int
    ) -> str:
        """
        Compose chunks in batches for very large files.
        All MinIO calls run in the thread pool.
        """
        intermediates = []
        
        for batch_idx in range(0, len(sources), batch_size):
            batch = sources[batch_idx:batch_idx + batch_size]
            intermediate_key = f"{upload.temp_prefix}intermediate_{batch_idx:06d}"
            
            await asyncio.to_thread(
                self.minio.compose_object,
                bucket_name=upload.temp_bucket,
                object_name=intermediate_key,
                sources=batch,
            )
            intermediates.append(intermediate_key)
        
        final_sources = [
            ComposeSource(upload.temp_bucket, key)
            for key in intermediates
        ]
        
        await asyncio.to_thread(
            self.minio.compose_object,
            bucket_name=upload.final_bucket,
            object_name=final_key,
            sources=final_sources,
        )
        
        # Cleanup intermediates
        for key in intermediates:
            try:
                await asyncio.to_thread(
                    self.minio.remove_object, upload.temp_bucket, key
                )
            except S3Error:
                pass
        
        return final_key
    
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
        """Delete temporary chunk files from MinIO (thread-pooled)."""
        for i in range(upload.total_chunks):
            chunk_key = f"{upload.temp_prefix}chunk_{i:08d}"
            try:
                await asyncio.to_thread(
                    self.minio.remove_object, upload.temp_bucket, chunk_key
                )
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
