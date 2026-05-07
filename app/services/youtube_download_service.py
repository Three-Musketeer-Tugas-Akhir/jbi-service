"""
YouTube video download service using yt-dlp.

Downloads YouTube videos in the background, tracks progress,
and feeds them into the existing pipeline (Upload → PipelineJob).
"""

import io
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Optional
from uuid import UUID, uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Progress Tracking ────────────────────────────────────────────────

class YTDownloadStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING_INFO = "extracting_info"
    DOWNLOADING = "downloading"
    UPLOADING_TO_STORAGE = "uploading_to_storage"
    CREATING_JOB = "creating_job"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class YTDownloadProgress:
    """Tracks the progress of a single YouTube download."""
    download_id: str
    url: str
    status: YTDownloadStatus = YTDownloadStatus.PENDING
    title: Optional[str] = None
    filename: Optional[str] = None
    release_date: Optional[str] = None
    file_size: int = 0
    downloaded_bytes: int = 0
    percent: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    error: Optional[str] = None
    job_id: Optional[str] = None  # PipelineJob ID once created
    user_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "download_id": self.download_id,
            "url": self.url,
            "status": self.status.value,
            "title": self.title,
            "filename": self.filename,
            "file_size": self.file_size,
            "downloaded_bytes": self.downloaded_bytes,
            "percent": round(self.percent, 1),
            "speed": self.speed,
            "eta": self.eta,
            "error": self.error,
            "job_id": self.job_id,
            "release_date": self.release_date,
            "created_at": self.created_at,
        }


# ── In-memory progress store (thread-safe) ───────────────────────────

_progress_store: Dict[str, YTDownloadProgress] = {}
_store_lock = threading.Lock()


def get_download_progress(download_id: str) -> Optional[YTDownloadProgress]:
    with _store_lock:
        return _progress_store.get(download_id)


def get_user_downloads(user_id: str) -> list[dict]:
    with _store_lock:
        return [
            p.to_dict()
            for p in _progress_store.values()
            if p.user_id == user_id
        ]


def _set_progress(progress: YTDownloadProgress):
    with _store_lock:
        _progress_store[progress.download_id] = progress


def _cleanup_old_entries(max_age_seconds: int = 3600):
    """Remove completed/failed entries older than max_age_seconds."""
    cutoff = time.time() - max_age_seconds
    with _store_lock:
        to_delete = [
            k for k, v in _progress_store.items()
            if v.status in (YTDownloadStatus.COMPLETED, YTDownloadStatus.FAILED)
            and v.created_at < cutoff
        ]
        for k in to_delete:
            del _progress_store[k]


# ── YouTube URL Validation ───────────────────────────────────────────

_YT_REGEX = re.compile(
    r'(https?://)?(www\.|m\.)?(youtube\.com|youtu\.be)/.+'
)


def is_valid_youtube_url(url: str) -> bool:
    return bool(_YT_REGEX.match(url.strip()))


# ── Core Download Logic (runs in background thread) ──────────────────

def _download_sync(download_id: str, url: str, temp_dir: str, output_template: str, progress: YTDownloadProgress):
    import yt_dlp
    
    # ── Step 1: Extract video info ───────────────────────────
    logger.info(f"[YT-DL {download_id}] Extracting info for: {url}")

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ValueError("Could not extract video info from URL")
        
        progress.title = info.get("title", "Untitled")
        progress.file_size = info.get("filesize") or info.get("filesize_approx") or 0
        progress.filename = f"{info.get('title', 'video')}.mp4"
        progress.release_date = info.get("upload_date")
        _set_progress(progress)

    logger.info(f"[YT-DL {download_id}] Title: {progress.title}")

    # ── Step 2: Download video ───────────────────────────────
    progress.status = YTDownloadStatus.DOWNLOADING
    _set_progress(progress)

    def _progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            progress.downloaded_bytes = downloaded
            if total > 0:
                progress.file_size = total
                progress.percent = (downloaded / total) * 100
            speed = d.get("speed")
            if speed:
                if speed > 1_000_000:
                    progress.speed = f"{speed / 1_000_000:.1f} MB/s"
                elif speed > 1_000:
                    progress.speed = f"{speed / 1_000:.0f} KB/s"
                else:
                    progress.speed = f"{speed:.0f} B/s"
            eta = d.get("eta")
            if eta is not None:
                mins, secs = divmod(int(eta), 60)
                progress.eta = f"{mins}:{secs:02d}"
            _set_progress(progress)
        elif d["status"] == "finished":
            progress.percent = 100.0
            progress.speed = None
            progress.eta = None
            _set_progress(progress)

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
        "merge_output_format": "mp4",
        "socket_timeout": 30,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find the downloaded file
    downloaded_files = list(Path(temp_dir).glob("*.*"))
    if not downloaded_files:
        raise FileNotFoundError("No file was downloaded by yt-dlp")

    temp_file_path = str(downloaded_files[0])
    actual_size = os.path.getsize(temp_file_path)
    actual_filename = downloaded_files[0].name

    # Sanitize filename for storage
    safe_filename = re.sub(r'[^\w\s\-\.\[\]]', '_', actual_filename)
    if not safe_filename.lower().endswith('.mp4'):
        safe_filename += '.mp4'

    progress.file_size = actual_size
    progress.filename = safe_filename
    progress.percent = 100.0
    _set_progress(progress)
    
    return temp_file_path, safe_filename, actual_size


async def _run_download_in_background(
    download_id: str,
    url: str,
    user_id: UUID,
    category: Optional[str] = None,
):
    """
    Async background task that:
    1. Uses yt-dlp (in thread executor) to extract info & download video
    2. Uploads the file to MinIO via UploadService
    3. Creates a PipelineJob via PipelineJobService
    """
    import asyncio
    
    progress = YTDownloadProgress(
        download_id=download_id,
        url=url,
        status=YTDownloadStatus.EXTRACTING_INFO,
        user_id=str(user_id),
    )
    _set_progress(progress)

    temp_dir = None

    try:
        temp_dir = tempfile.mkdtemp(prefix="ytdl_")
        output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")

        # Run the blocking yt-dlp part in an executor
        loop = asyncio.get_running_loop()
        temp_file_path, safe_filename, actual_size = await loop.run_in_executor(
            None,
            _download_sync,
            download_id,
            url,
            temp_dir,
            output_template,
            progress
        )

        logger.info(
            f"[YT-DL {download_id}] Downloaded: {safe_filename} "
            f"({actual_size} bytes)"
        )

        # ── Step 3: Upload to MinIO & create pipeline job ────────
        progress.status = YTDownloadStatus.UPLOADING_TO_STORAGE
        _set_progress(progress)

        job_id = await _upload_to_storage_and_create_job(
            download_id=download_id,
            file_path=temp_file_path,
            filename=safe_filename,
            file_size=actual_size,
            user_id=user_id,
            category=category,
            progress=progress,
        )
        progress.job_id = str(job_id)

        # ── Done ─────────────────────────────────────────────────
        progress.status = YTDownloadStatus.COMPLETED
        progress.percent = 100.0
        _set_progress(progress)

        logger.info(
            f"[YT-DL {download_id}] Complete! PipelineJob: {progress.job_id}"
        )

    except Exception as e:
        logger.error(f"[YT-DL {download_id}] Failed: {e}", exc_info=True)
        progress.status = YTDownloadStatus.FAILED
        progress.error = str(e)
        _set_progress(progress)

    finally:
        # Cleanup temp files
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_err:
                logger.warning(f"[YT-DL {download_id}] Cleanup failed: {cleanup_err}")

        # Periodically clean old entries
        _cleanup_old_entries()


async def _upload_to_storage_and_create_job(
    download_id: str,
    file_path: str,
    filename: str,
    file_size: int,
    user_id: UUID,
    category: Optional[str],
    progress: YTDownloadProgress,
) -> UUID:
    """
    Upload the downloaded file to MinIO and create a PipelineJob record.
    
    This mirrors what _assemble_and_create_job does in upload.py,
    but takes a local file instead of assembled chunks.
    """
    from minio import Minio
    from sqlalchemy import select

    from app.db.models import User, PipelineJob, Upload
    from app.db.models.pipeline import JobStatus
    from app.db.session import async_session
    from app.services.pipeline_job_service import PipelineJobService

    async with async_session() as db:
        try:
            # Get user
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise ValueError(f"User {user_id} not found")

            # Upload file to MinIO directly using standard bucket
            minio_client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region=settings.minio_region,
            )

            bucket = settings.minio_bucket_name
            if not minio_client.bucket_exists(bucket):
                minio_client.make_bucket(bucket)

            # Generate Job ID upfront for path construction
            job_id = uuid4()

            # Upload to MinIO with standard job path
            minio_key = f"jobs/{job_id}/original/{filename}"

            with open(file_path, "rb") as f:
                minio_client.put_object(
                    bucket_name=bucket,
                    object_name=minio_key,
                    data=f,
                    length=file_size,
                    content_type="video/mp4",
                )

            logger.info(f"[YT-DL {download_id}] Uploaded to MinIO: {minio_key}")

            # Create Upload record (for consistency with existing flow)
            upload_record = Upload(
                upload_id=download_id,
                filename=filename,
                file_size=file_size,
                mime_type="video/mp4",
                status="complete",
                chunk_size=file_size,  # single "chunk"
                total_chunks=1,
                chunks_received=[0],
                chunks_uploading=[],
                temp_bucket="temp-uploads",
                temp_prefix=f"uploads/{user_id}/{download_id}/",
                final_bucket=bucket,
                final_key=minio_key,
                category=category,
                user_id=user_id,
                completed_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            db.add(upload_record)
            await db.flush()

            # Create PipelineJob via the service
            progress.status = YTDownloadStatus.CREATING_JOB
            _set_progress(progress)

            pipeline_service = PipelineJobService(db)
            job = await pipeline_service.create_pipeline_job(upload_record, user, job_id=job_id)
            
            # Save the release date from YouTube
            if progress.release_date:
                job.release_date = progress.release_date

            await db.commit()

            logger.info(
                f"[YT-DL {download_id}] Created PipelineJob {job.id} "
                f"for YouTube video: {filename}"
            )
            return job.id

        except Exception as e:
            await db.rollback()
            raise


# ── Public API ───────────────────────────────────────────────────────

def start_youtube_download(
    url: str,
    user_id: UUID,
    background_tasks,
    category: Optional[str] = None,
) -> str:
    """
    Start a YouTube video download in an async background task.
    
    Args:
        url: YouTube video URL
        user_id: Requesting user's ID
        background_tasks: FastAPI BackgroundTasks instance
        category: Optional sign language category (SIBI/BISINDO)
        
    Returns:
        download_id for tracking progress
        
    Raises:
        ValueError: If URL is not a valid YouTube URL
    """
    if not is_valid_youtube_url(url):
        raise ValueError(
            f"Invalid YouTube URL: {url}. "
            "Must be a youtube.com or youtu.be link."
        )

    download_id = str(uuid4())

    # Initialize progress entry
    progress = YTDownloadProgress(
        download_id=download_id,
        url=url,
        status=YTDownloadStatus.PENDING,
        user_id=str(user_id),
    )
    _set_progress(progress)

    # Start background task via FastAPI
    background_tasks.add_task(
        _run_download_in_background,
        download_id=download_id,
        url=url,
        user_id=user_id,
        category=category,
    )

    logger.info(f"[YT-DL {download_id}] Started async background download for: {url}")
    return download_id
