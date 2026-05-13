"""
Tus Protocol API endpoints for chunked file uploads.

Implements Tus 1.0.0 protocol for resumable uploads:
- POST /files - Create upload
- HEAD /files/{id} - Get upload status
- PATCH /files/{id} - Upload chunk
- DELETE /files/{id} - Cancel upload
"""

import asyncio
import base64
import logging
from typing import Optional
from uuid import UUID

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

from app.api.deps import get_current_user
from app.core.exceptions import NotFoundError, ValidationError, StorageError
from app.db.models import User
from app.db.session import async_session
from app.services.upload_service import UploadService
from app.services.pipeline_job_service import PipelineJobService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])


# ── Tus Protocol Endpoints ────────────────────────────────────────────

@router.options("/files")
async def tus_options():
    """
    Tus protocol discovery endpoint.
    Returns supported Tus extensions and version.
    """
    return Response(
        status_code=200,
        headers={
            "Tus-Resumable": "1.0.0",
            "Tus-Version": "1.0.0",
            "Tus-Max-Size": str(UploadService.MAX_FILE_SIZE),
            "Tus-Extension": "creation,termination",
        }
    )


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: Request,
    upload_length: int = Header(..., alias="Upload-Length", description="Total file size in bytes"),
    upload_metadata: Optional[str] = Header(None, alias="Upload-Metadata", description="Base64-encoded metadata"),
    current_user: User = Depends(get_current_user),
):
    """
    Create new upload resource (Tus Protocol).
    
    Headers:
        Upload-Length: Total file size in bytes (max 10GB)
        Upload-Metadata: Base64-encoded metadata (filename, filetype, category)
    
    Returns:
        201 Created
        Location: /api/v1/upload/files/{upload_id}
        Tus-Resumable: 1.0.0
    """
    try:
        async with async_session() as db:
            upload_service = UploadService(db)
            upload = await upload_service.create_upload(
                user=current_user,
                file_size=upload_length,
                metadata=upload_metadata
            )
            await db.commit()
        
        logger.info(
            f"Created upload {upload.upload_id} for user {current_user.id}: "
            f"{upload.filename} ({upload_length} bytes)"
        )
        
        return Response(
            status_code=status.HTTP_201_CREATED,
            headers={
                "Location": f"/api/v1/upload/files/{upload.upload_id}",
                "Upload-Id": upload.upload_id,
                "Tus-Resumable": "1.0.0",
                "Tus-Version": "1.0.0",
                "Tus-Max-Size": str(UploadService.MAX_FILE_SIZE),
                "Content-Length": "0",
            }
        )
        
    except ValidationError as e:
        logger.warning(f"Validation error creating upload: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create upload: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create upload: {str(e)}")


@router.head("/files/{upload_id}")
async def get_upload_status(
    upload_id: str,
    current_user: User = Depends(get_current_user),
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
        async with async_session() as db:
            upload_service = UploadService(db)
            offset = await upload_service.get_upload_offset(upload_id, current_user.id)
            upload = await upload_service.get_upload(upload_id, current_user.id)
            
            headers = {
                "Upload-Offset": str(offset),
                "Upload-Length": str(upload.file_size),
                "Upload-Status": upload.status,
                "Tus-Resumable": "1.0.0",
                "Cache-Control": "no-store",
                "Content-Length": "0",
            }
            
            # Add Upload-Metadata if available
            if upload.category or upload.filename:
                metadata_parts = []
                if upload.filename:
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
    content_length: Optional[int] = Header(None, alias="Content-Length", description="Chunk size in bytes"),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a file chunk (Tus Protocol).
    
    Headers:
        Upload-Offset: Byte offset for this chunk
        Content-Length: Chunk size (optional, validated if present)
        Content-Type: application/offset+octet-stream (not validated)
    
    Body:
        Raw chunk bytes
    
    Returns:
        204 No Content on success
        Upload-Offset header with new offset
    """
    try:
        # Read chunk data from raw body
        chunk_data = await request.body()
        
        if not chunk_data:
            raise HTTPException(status_code=400, detail="Empty chunk body")
        
        # Validate content length if provided (optional — some clients don't send it)
        if content_length is not None and len(chunk_data) != content_length:
            logger.warning(
                f"Content-Length mismatch for upload {upload_id}: "
                f"header={content_length}, actual={len(chunk_data)}"
            )
            # Don't reject — use actual data length
        
        logger.debug(
            f"Received chunk for upload {upload_id}: "
            f"offset={upload_offset}, size={len(chunk_data)}"
        )
        
        # Store chunk using short DB transaction
        async with async_session() as db:
            upload_service = UploadService(db)
            
            new_offset = await upload_service.store_chunk(
                upload_id=upload_id,
                user_id=current_user.id,
                chunk_data=chunk_data,
                offset=upload_offset
            )
            
            # Check if upload is complete
            upload = await upload_service.get_upload(upload_id, current_user.id)
            is_complete = upload.status == "assembling"
            
            await db.commit()
        
        # Trigger background assembly if complete (outside DB transaction)
        if is_complete:
            # Small delay to ensure commit is fully propagated
            background_tasks.add_task(
                _assemble_and_create_job,
                upload_id,
                current_user.id,
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
        raise HTTPException(status_code=409, detail=str(e))
    except StorageError as e:
        logger.error(f"Storage error uploading chunk: {e}")
        raise HTTPException(status_code=500, detail="Storage error")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload chunk for {upload_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload chunk: {str(e)}")


async def _assemble_and_create_job(
    upload_id: str,
    user_id: UUID,
):
    """
    Background task to assemble file and create pipeline job.
    
    Called when all chunks are received.
    """
    # Small delay to ensure the DB commit from PATCH handler is fully visible
    await asyncio.sleep(1.0)
    
    async with async_session() as db:
        try:
            logger.info(f"Starting assembly for upload {upload_id}")
            
            upload_service = UploadService(db)
            pipeline_service = PipelineJobService(db)
            
            # Get upload
            upload = await upload_service.get_upload(upload_id, user_id)
            
            if upload.status != "assembling":
                logger.warning(
                    f"Upload {upload_id} status is '{upload.status}', expected 'assembling'. Skipping."
                )
                return
            
            # Assemble file
            final_key = await upload_service.assemble_file(upload)
            upload.final_key = final_key
            
            # Get user
            from sqlalchemy import select
            from app.db.models import User
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                raise Exception(f"User {user_id} not found")
            
            # Create pipeline job (pass dataset_id from upload metadata)
            job = await pipeline_service.create_pipeline_job(
                upload, user, dataset_id=upload.dataset_id
            )
            
            await db.commit()
            
            logger.info(
                f"Upload {upload_id} complete. Created pipeline job {job.id}. "
                f"File key: {final_key}"
            )
            
            # Cleanup temp chunks after successful assembly
            try:
                await upload_service._cleanup_temp_chunks(upload)
                logger.info(f"Cleaned up temp chunks for upload {upload_id}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp chunks: {cleanup_error}")
            
        except Exception as e:
            logger.error(f"Failed to assemble upload {upload_id}: {e}", exc_info=True)
            # Mark upload as failed
            try:
                upload = await upload_service.get_upload(upload_id, user_id)
                upload.status = "failed"
                await db.commit()
            except Exception as cleanup_error:
                logger.error(f"Failed to mark upload as failed: {cleanup_error}")


@router.delete("/files/{upload_id}")
async def cancel_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel upload and cleanup temporary chunks (Tus Protocol).
    
    Returns:
        204 No Content on success
        404 Not Found if upload doesn't exist
    """
    try:
        async with async_session() as db:
            upload_service = UploadService(db)
            await upload_service.cancel_upload(upload_id, current_user.id)
            await db.commit()
        
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


@router.get("/files/{upload_id}/status")
async def get_detailed_status(
    upload_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed upload status including pipeline job info.
    
    Returns:
        JSON with upload status and job details
    """
    try:
        async with async_session() as db:
            upload_service = UploadService(db)
            pipeline_service = PipelineJobService(db)
            
            upload = await upload_service.get_upload(upload_id, current_user.id)
            
            chunks_received_count = len(upload.chunks_received or [])
            
            result = {
                "upload_id": upload.upload_id,
                "filename": upload.filename,
                "status": upload.status,
                "file_size": upload.file_size,
                "chunks_received": chunks_received_count,
                "total_chunks": upload.total_chunks,
                "progress_percent": round(
                    (chunks_received_count / upload.total_chunks) * 100, 2
                ) if upload.total_chunks > 0 else 0,
                "created_at": upload.created_at.isoformat() if upload.created_at else None,
                "expires_at": upload.expires_at.isoformat() if upload.expires_at else None,
            }
            
            # Add job info if available
            if upload.job_id:
                pipeline_status = await pipeline_service.get_pipeline_status(upload.job_id)
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
        async with async_session() as db:
            upload_service = UploadService(db)
            count = await upload_service.cleanup_stale_uploads(max_age_hours)
            await db.commit()
        
        return {
            "cleaned": count,
            "max_age_hours": max_age_hours
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup uploads: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup uploads")


from fastapi import BackgroundTasks

@router.post("/youtube", status_code=status.HTTP_202_ACCEPTED)
async def start_youtube_download(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """
    Start a YouTube video download in the background.
    
    Request body (JSON):
        url: YouTube video URL (required)
        category: Sign language category - SIBI or BISINDO (optional)
    
    Returns:
        202 Accepted with download_id for progress tracking
    """
    from app.services.youtube_download_service import (
        start_youtube_download as _start_download,
        is_valid_youtube_url,
    )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    url = body.get("url", "").strip()
    category = body.get("category")
    dataset_id = body.get("dataset_id")

    if not url:
        raise HTTPException(status_code=400, detail="YouTube URL is required")

    if not is_valid_youtube_url(url):
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL. Must be a youtube.com or youtu.be link.",
        )

    if category and category not in ("SIBI", "BISINDO"):
        raise HTTPException(
            status_code=400,
            detail="Category must be 'SIBI' or 'BISINDO'",
        )
    
    # Parse dataset_id
    dataset_uuid = None
    if dataset_id:
        from uuid import UUID
        try:
            dataset_uuid = UUID(dataset_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid dataset_id: {dataset_id}")

    try:
        download_id = _start_download(
            url=url,
            user_id=current_user.id,
            background_tasks=background_tasks,
            category=category,
            dataset_id=dataset_uuid,
        )

        logger.info(
            f"YouTube download started: {download_id} by user {current_user.id} "
            f"for URL: {url}"
        )

        return {
            "download_id": download_id,
            "url": url,
            "status": "pending",
            "message": "YouTube download started. Use GET /upload/youtube/{download_id} to track progress.",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start YouTube download: {e}")
        raise HTTPException(status_code=500, detail="Failed to start download")


@router.get("/youtube/{download_id}")
async def get_youtube_download_progress(
    download_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get progress of a YouTube download.
    
    Returns download status including percent, speed, ETA, and
    the pipeline job_id once the download completes.
    """
    from app.services.youtube_download_service import get_download_progress

    progress = get_download_progress(download_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Download not found")

    # Verify ownership
    if progress.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail="Download not found")

    return progress.to_dict()


@router.get("/youtube")
async def list_youtube_downloads(
    current_user: User = Depends(get_current_user),
):
    """
    List all active YouTube downloads for the current user.
    """
    from app.services.youtube_download_service import get_user_downloads

    downloads = get_user_downloads(str(current_user.id))
    return {"downloads": downloads}
