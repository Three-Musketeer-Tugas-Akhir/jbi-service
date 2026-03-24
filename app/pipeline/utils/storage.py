"""
Storage utilities for pipeline.

S3/MinIO operations - pure I/O, no business logic.
"""

import logging
from typing import Optional

from app.services.minio_service import get_minio_service

logger = logging.getLogger(__name__)


async def download_video(video_key: str, local_path: str) -> bytes:
    """
    Download video from storage.
    
    Args:
        video_key: S3/MinIO object key
        local_path: Local file path to save
        
    Returns:
        Downloaded file bytes
    """
    minio_service = get_minio_service()
    return await minio_service.download_file(video_key)


async def upload_segment(local_path: str, segment_key: str) -> str:
    """
    Upload processed segment to storage.
    
    Args:
        local_path: Local file path
        segment_key: S3/MinIO object key
        
    Returns:
        Storage URL
    """
    minio_service = get_minio_service()
    return await minio_service.upload_file(local_path, segment_key)


async def get_presigned_url(object_key: str, expiry: int = 3600) -> str:
    """
    Generate presigned URL for object access.
    
    Args:
        object_key: S3/MinIO object key
        expiry: URL expiration in seconds
        
    Returns:
        Presigned URL string
    """
    minio_service = get_minio_service()
    return await minio_service.get_presigned_url(object_key, expiry)
