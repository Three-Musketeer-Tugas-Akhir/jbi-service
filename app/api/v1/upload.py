"""
Tus Protocol API endpoints for chunked file uploads.

Implements Tus 1.0.0 protocol for resumable uploads:
- POST /files - Create upload
- HEAD /files/{id} - Get upload status
- PATCH /files/{id} - Upload chunk
- DELETE /files/{id} - Cancel upload
"""

import logging
from typing import Optional

from fastapi import (
    APIRouter, 
    Request, 
    Response, 
    Header, 
    HTTPException, 
    Depends, 
    status,
    BackgroundTasks
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import NotFoundError, ValidationError, StorageError
from app.db.models import User, Upload
from app.db.session import get_db
from app.services.upload_service import UploadService
from app.services.pipeline_job_service import PipelineJobService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])


# ── Helper Functions ─────────────────────────────────────────────────

async def get_upload_service(db: Session = Depends(get_db)) -> UploadService:
    """Dependency to get UploadService with database session."""
    return UploadService(db)


async def get_pipeline_job_service(db: Session = Depends(get_db)) -> PipelineJobService:
    """Dependency to get PipelineJobService with database session."""
    return PipelineJobService(db)


# ── Tus Protocol Endpoints ────────────────────────────────────────────

@router.post("/files", status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: Request,
    upload_length: int = Header(..., alias="Upload-Length", description="Total file size in bytes"),
    upload_metadata: Optional[str] = Header(None, alias="Upload-Metadata", description="Base64-encoded metadata"),
    content_type: Optional[str] = Header(None, alias="Content-Type"),
    current_user: User = Depends(get_current_user),
    upload_service: UploadService = Depends(get_upload_service),
):
    """
    Create new upload resource (Tus Protocol).
    
    Headers:
        Upload-Length: Total file size in bytes (max 10GB)
        Upload-Metadata: Base64-encoded metadata (filename, filetype, category)
        Content-Type: application/offset+octet-stream
    
    Returns:
        201 Created
        Location: /api/v1/upload/files/{upload_id}
        Tus-Resumable: 1.0.0
    """
    try:
        upload = upload_service.create_upload(
            user=current_user,
            file_size=upload_length,
            metadata=upload_metadata
        )
        
        logger.info(
            f"Created upload {upload.upload_id} for user {current_user.id}: "
            f"{upload.filename} ({upload_length} bytes)"
        )
        
        return Response(
            status_code=status.HTTP_201_CREATED,
            headers={
                "Location": f"/api/v1/upload/files/{upload.upload_id}",
                "Tus-Resumable": "1.0.0",
                "Tus-Version": "1.0.0",
                "Tus-Max-Size": str(UploadService.MAX_FILE_SIZE),
                "Content-Length": "0",
            }
        )
        
    except ValidationError as e:
        logger.warning(f"Validation error creating upload: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create upload: {e}")
        raise HTTPException(status_code=500, detail="Failed to create upload")


@router.head("/files/{upload_id}")
async def get_upload_status(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    upload_service: UploadService = Depends(get_upload_service),
):
    """
    Get upload status and current offset (Tus Protocol).
    
    Used for resuming interrupted uploads.
    
    Headers:
        Upload-Offset: Number of bytes received
        Upload-Length: Total file size
        Cache-Control: no-store
    
    Returns:
        200 OK with Tus headers
        404 Not Found if upload doesn't exist
    """
    try:
        offset = upload_service.get_upload_offset(upload_id, current_user.id)
        upload = upload_service.get_upload(upload_id, current_user.id)
        
        headers = {
            "Upload-Offset": str(offset),
            "Upload-Length": str(upload.file_size),
            "Tus-Resumable": "1.0.0",
            "Cache-Control": "no-store",
            "Content-Length": "0",
        }
        
        # Add Upload-Metadata if available
        if upload.category or upload.filename:
            metadata_parts = []
            if upload.filename:
                import base64
                filename_b64 = base64.b64encode(upload.filename.encode()).decode()
                metadata_parts.append(f"filename {filename_b64}")
            if upload.category:
                category_b64 = base64.b64encode(upload.category.encode()).decode()
                metadata_parts.append(f"category {category_b64}")
            if metadata_parts:
                headers["Upload-Metadata"] = ",".join(metadata_parts)
        
        return Response(status_code=200, headers=headers)
        
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Upload not found")
    except Exception as e:
        logger.error(f"Failed to get upload status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get upload status")


@router.patch("/files/{upload_id}")
async def upload_chunk(
    upload_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    upload_offset: int = Header(..., alias="Upload-Offset", description="Byte offset for this chunk"),
    content_length: int = Header(..., alias="Content-Length", description="Chunk size in bytes"),
    upload_checksum: Optional[str] = Header(None, alias="Upload-Checksum", description="Optional checksum"),
    content_type: str = Header(..., alias="Content-Type"),
    current_user: User = Depends(get_current_user),
    upload_service: UploadService = Depends(get_upload_service),
    pipeline_service: PipelineJobService = Depends(get_pipeline_job_service),
):
    """
    Upload a file chunk (Tus Protocol).
    
    Supports parallel uploads - chunks can arrive in any order.
    
    Headers:
        Upload-Offset: Byte offset for this chunk
        Content-Length: Chunk size (max 5MB)
        Upload-Checksum: Optional checksum (sha256 base64)
        Content-Type: application/offset+octet-stream
    
    Body:
        Raw chunk bytes
    
    Returns:
        204 No Content on success
        Upload-Offset header with new offset
    """
    try:
        # Read chunk data
        chunk_data = await request.body()
        
        # Validate content length
        if len(chunk_data) != content_length:
            raise HTTPException(
                status_code=400, 
                detail=f"Content-Length mismatch: header={content_length}, actual={len(chunk_data)}"
            )
        
        # Verify checksum if provided
        if upload_checksum:
            try:
                import hashlib
                import base64
                
                # Parse checksum header (format: "sha256 base64value")
                algo, checksum_b64 = upload_checksum.split(" ", 1)
                if algo.lower() != "sha256":
                    raise HTTPException(status_code=400, detail="Only sha256 checksums supported")
                
                calculated = hashlib.sha256(chunk_data).digest()
                expected = base64.b64decode(checksum_b64)
                
                if calculated != expected:
                    raise HTTPException(status_code=460, detail="Checksum mismatch")
                    
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Checksum verification failed: {e}")
                # Continue anyway - checksum is optional
        
        # Store chunk
        new_offset = upload_service.store_chunk(
            upload_id=upload_id,
            user_id=current_user.id,
            chunk_data=chunk_data,
            offset=upload_offset
        )
        
        # Check if upload is complete (all chunks received)
        upload = upload_service.get_upload(upload_id, current_user.id)
        
        if upload.status == "assembling":
            # Trigger file assembly and job creation in background
            background_tasks.add_task(
                _assemble_and_create_job,
                upload_id,
                current_user.id,
                upload_service,
                pipeline_service
            )
        
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={
                "Upload-Offset": str(new_offset),
                "Tus-Resumable": "1.0.0",
            }
        )
        
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Upload not found")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        logger.error(f"Storage error uploading chunk: {e}")
        raise HTTPException(status_code=500, detail="Storage error")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload chunk: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload chunk")


async def _assemble_and_create_job(
    upload_id: str,
    user_id: str,
    upload_service: UploadService,
    pipeline_service: PipelineJobService,
):
    """
    Background task to assemble file and create pipeline job.
    
    Called when all chunks are received.
    """
    try:
        logger.info(f"Starting assembly for upload {upload_id}")
        
        # Get upload
        upload = upload_service.get_upload(upload_id, user_id)
        
        # Assemble file
        final_key = upload_service.assemble_file(upload)
        upload.final_key = final_key
        
        # Get user
        user = upload_service.db.query(User).filter(User.id == user_id).first()
        
        # Create pipeline job
        job = await pipeline_service.create_pipeline_job(upload, user)
        
        logger.info(
            f"Upload {upload_id} complete. Created pipeline job {job.id}"
        )
        
    except Exception as e:
        logger.error(f"Failed to assemble upload {upload_id}: {e}")
        # Mark upload as failed
        try:
            upload = upload_service.get_upload(upload_id, user_id)
            upload.status = "failed"
            upload_service.db.commit()
        except Exception as cleanup_error:
            logger.error(f"Failed to mark upload as failed: {cleanup_error}")


@router.delete("/files/{upload_id}")
async def cancel_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    upload_service: UploadService = Depends(get_upload_service),
):
    """
    Cancel upload and cleanup temporary chunks (Tus Protocol).
    
    Returns:
        204 No Content on success
        404 Not Found if upload doesn't exist
    """
    try:
        upload_service.cancel_upload(upload_id, current_user.id)
        
        logger.info(f"Cancelled upload {upload_id}")
        
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"Tus-Resumable": "1.0.0"}
        )
        
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Upload not found")
    except Exception as e:
        logger.error(f"Failed to cancel upload: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel upload")


# ── Additional Endpoints ─────────────────────────────────────────────

@router.get("/files/{upload_id}/status")
async def get_detailed_status(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    upload_service: UploadService = Depends(get_upload_service),
    pipeline_service: PipelineJobService = Depends(get_pipeline_job_service),
):
    """
    Get detailed upload status including pipeline job info.
    
    Returns:
        JSON with upload status and job details
    """
    try:
        upload = upload_service.get_upload(upload_id, current_user.id)
        
        result = {
            "upload_id": upload.upload_id,
            "filename": upload.filename,
            "status": upload.status,
            "file_size": upload.file_size,
            "chunks_received": len(upload.chunks_received),
            "total_chunks": upload.total_chunks,
            "progress_percent": round(
                (len(upload.chunks_received) / upload.total_chunks) * 100, 2
            ) if upload.total_chunks > 0 else 0,
            "created_at": upload.created_at.isoformat() if upload.created_at else None,
            "expires_at": upload.expires_at.isoformat() if upload.expires_at else None,
        }
        
        # Add job info if available
        if upload.job_id:
            pipeline_status = pipeline_service.get_pipeline_status(upload.job_id)
            result["pipeline_job"] = pipeline_status
        
        return result
        
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Upload not found")
    except Exception as e:
        logger.error(f"Failed to get upload status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get upload status")


@router.post("/cleanup")
async def cleanup_stale_uploads(
    current_user: User = Depends(get_current_user),
    upload_service: UploadService = Depends(get_upload_service),
    max_age_hours: int = 24,
):
    """
    Admin endpoint to cleanup stale uploads.
    
    Requires admin privileges.
    """
    # Check admin permission
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        count = upload_service.cleanup_stale_uploads(max_age_hours)
        
        return {
            "cleaned": count,
            "max_age_hours": max_age_hours
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup uploads: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup uploads")
