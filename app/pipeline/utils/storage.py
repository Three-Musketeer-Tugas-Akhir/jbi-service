"""
Storage utilities for pipeline.

S3/MinIO operations - pure I/O, no business logic.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from app.services.minio_service import get_minio_service
from app.core.config import settings

logger = logging.getLogger(__name__)


async def download_video(video_key: str, local_path: Optional[str] = None) -> bytes:
    """
    Download video from storage.
    
    Args:
        video_key: S3/MinIO object key
        local_path: Optional local file path (not used, kept for compatibility)
        
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


class StorageManager:
    """
    Manager for local storage paths during pipeline processing.
    
    Organizes output files by job and stage.
    """
    
    def __init__(self, base_dir: Optional[str] = None):
        """
        Initialize storage manager.
        
        Args:
            base_dir: Base directory for all pipeline outputs.
                     Defaults to settings.STORAGE_LOCAL_PATH or /tmp/jbi-pipeline
        """
        if base_dir:
            self.base_dir = Path(base_dir)
        elif hasattr(settings, 'STORAGE_LOCAL_PATH'):
            self.base_dir = Path(settings.STORAGE_LOCAL_PATH)
        else:
            self.base_dir = Path("/tmp/jbi-pipeline")
    
    def get_job_dir(self, job_id: str) -> Path:
        """Get base directory for a job."""
        return self.base_dir / "jobs" / job_id
    
    def get_stage1_output_dir(self, job_id: str) -> Path:
        """Get Stage 1 (detection) output directory."""
        return self.get_job_dir(job_id) / "stage1"
    
    def get_stage2_output_dir(self, job_id: str) -> str:
        """
        Get Stage 2 (cropping) output directory.
        
        Args:
            job_id: Pipeline job ID
            
        Returns:
            Path to Stage 2 output directory as string
        """
        path = self.get_job_dir(job_id) / "stage2"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    
    def get_audio_output_dir(self, job_id: str) -> Path:
        """Get audio extraction output directory."""
        return self.get_job_dir(job_id) / "audio"
    
    def cleanup_job(self, job_id: str) -> bool:
        """
        Remove all local files for a job.
        
        Args:
            job_id: Pipeline job ID
            
        Returns:
            True if cleanup successful
        """
        import shutil
        job_dir = self.get_job_dir(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
            logger.info(f"Cleaned up job directory: {job_dir}")
            return True
        return False
