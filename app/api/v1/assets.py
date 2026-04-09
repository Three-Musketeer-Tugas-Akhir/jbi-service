"""
Assets API Router.

Provides authenticated access to MinIO S3 stored files with authorization checks.
Supports video streaming with HTTP Range requests.
"""

import logging
import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_user
from app.db.models import User, PipelineJob
from app.db.session import async_session
from app.services.minio_service import get_minio_service
from app.services.streaming_token_service import streaming_token_service
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assets"])

# Allowed file extensions for security
ALLOWED_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.json', '.txt'}

# Path pattern: jobs/{uuid}/...
JOB_PATH_PATTERN = re.compile(
    r'^jobs/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/(.+)$',
    re.IGNORECASE
)


def validate_path(path: str) -> tuple[UUID, str]:
    """
    Validate and parse asset path.
    
    Args:
        path: Full object path from URL
        
    Returns:
        Tuple of (job_id, relative_path)
        
    Raises:
        ValueError: If path is invalid
    """
    # Check for path traversal attempts
    if '..' in path or '~' in path or path.startswith('/'):
        raise ValueError("Invalid path: path traversal detected")
    
    # Check file extension
    file_ext = '.' + path.split('.')[-1].lower() if '.' in path else ''
    if file_ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file type: {file_ext}")
    
    # Parse job path pattern
    match = JOB_PATH_PATTERN.match(path)
    if not match:
        raise ValueError("Invalid path format: expected jobs/{uuid}/...")
    
    job_id_str, relative_path = match.groups()
    
    try:
        job_id = UUID(job_id_str)
    except ValueError:
        raise ValueError(f"Invalid UUID: {job_id_str}")
    
    return job_id, relative_path


async def authorize_access(
    user: User,
    job_id: UUID,
    session: AsyncSession
) -> bool:
    """
    Check if user is authorized to access job assets.
    
    Args:
        user: Current authenticated user
        job_id: UUID of the job
        session: Database session
        
    Returns:
        True if authorized, False otherwise
    """
    # Admin can access all
    if user.has_role("admin"):
        return True
    
    # Get job owner
    result = await session.execute(
        select(PipelineJob).where(PipelineJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        return False
    
    # Check ownership
    return str(job.created_by) == str(user.id)


def get_content_type(filename: str) -> str:
    """Determine Content-Type based on file extension."""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    mime_types = {
        'mp4': 'video/mp4',
        'avi': 'video/x-msvideo',
        'mkv': 'video/x-matroska',
        'mov': 'video/quicktime',
        'webm': 'video/webm',
        'json': 'application/json',
        'txt': 'text/plain',
    }
    return mime_types.get(ext, 'application/octet-stream')


def get_current_user_optional(
    token: str = Depends(get_current_user)
) -> Optional[User]:
    """Dependency that allows optional authentication."""
    try:
        return token
    except Exception:
        return None


@router.get("/{path:path}")
async def get_asset(
    path: str,
    token: Optional[str] = Query(None, description="Streaming token for video access (alternative to JWT)"),
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Stream an asset file from MinIO S3 storage.
    
    **Path Pattern:** `jobs/{job_id}/...`
    
    **Authorization (one of):**
    1. Streaming token via `?token=` query parameter (for video players)
    2. JWT token via `Authorization: Bearer {token}` header (for API clients)
    
    **Examples:**
    - `/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4?token=xyz`
    - `/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4` (with Authorization header)
    
    **Headers:**
    - `Authorization: Bearer {jwt_token}` (required if no streaming token)
    - `Range: bytes=0-1023` (optional, for video seeking)
    """
    # Validate path
    try:
        job_id, relative_path = validate_path(path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    # Determine user_id from token or JWT
    user_id = None
    is_streaming_token = False
    
    if token:
        # Verify streaming token
        user_id_from_token = streaming_token_service.verify_token(token, path)
        if user_id_from_token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired streaming token"
            )
        user_id = user_id_from_token
        is_streaming_token = True
    else:
        # Use JWT authentication
        user_id = current_user.id
    
    # Check authorization (skip if using valid streaming token)
    if not is_streaming_token:
        async with async_session() as session:
            is_authorized = await authorize_access(current_user, job_id, session)
            
            if not is_authorized:
                logger.warning(
                    f"Unauthorized access attempt: user={current_user.id}, "
                    f"job={job_id}, path={path}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this resource"
                )
    
    # Stream file from MinIO
    minio_service = get_minio_service()
    bucket_name = settings.minio_bucket_name
    
    try:
        # Get object from MinIO
        response = minio_service.client.get_object(bucket_name, path)
        
        # Determine content type
        content_type = get_content_type(path)
        
        # Build response headers
        headers = {
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",  # 1 hour cache
        }
        
        # Add filename for download (optional)
        filename = path.split('/')[-1]
        headers["Content-Disposition"] = f"inline; filename=\"{filename}\""
        
        # Generator to stream content and ensure cleanup
        def iterfile():
            try:
                for chunk in response.stream(amt=8192):  # 8KB chunks
                    yield chunk
            finally:
                response.close()
                response.release_conn()
        
        # Return streaming response
        return StreamingResponse(
            content=iterfile(),
            headers=headers,
            media_type=content_type,
        )
        
    except Exception as e:
        error_msg = str(e).lower()
        if "nosuchkey" in error_msg or "not found" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        logger.error(f"Error streaming asset {path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve file"
        )
