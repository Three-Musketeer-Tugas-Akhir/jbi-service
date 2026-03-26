"""
Detection Worker - Stage 1 Queue Consumer

Processes detection jobs from the queue using YOLOv8.
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from uuid import UUID
from typing import Dict, Any, Optional

from app.workers.base import BaseWorker
from app.pipeline.stages.stage1_detection import JBIDetector
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.queue_service import queue_service
from app.services.minio_service import get_minio_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus, PipelineSegment
from app.core.exceptions import ProcessingError

logger = logging.getLogger(__name__)


class DetectionWorker(BaseWorker):
    """
    Worker that processes detection jobs from the queue.
    
    Consumes jobs from 'detection' queue, runs YOLO inference,
    creates segments, and queues next stage (ASR).
    """
    
    queue_name = "detection"
    max_retries = 3
    
    def __init__(self):
        super().__init__()
        self.minio_service = get_minio_service()
        self.detector = JBIDetector()
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a detection job.
        
        Args:
            payload: {"job_id": str, "video_path": str, "video_key": str}
            
        Returns:
            {"segments_detected": int, "confidence": float}
        """
        job_id = UUID(payload["job_id"])
        video_key = payload.get("video_key")
        
        logger.info(f"Processing detection job: {job_id}")
        
        # Update status to DETECTING
        async with async_session() as session:
            job_repo = JobRepository(session)
            await job_repo.update_status(job_id, "DETECTING")
            await session.commit()
        
        # Download video from MinIO
        temp_video = None
        try:
            if video_key:
                video_data = await self.minio_service.download_file(video_key)
                temp_video = self._save_temp_video(video_data, job_id)
                video_path = str(temp_video)
            else:
                video_path = payload.get("video_path")
            
            # Run detection (pure ML, no DB)
            segments = await self._run_detection(video_path, job_id)
            
            if not segments:
                logger.warning(f"No segments detected for job {job_id}")
                # Update job status and complete
                async with async_session() as session:
                    job_repo = JobRepository(session)
                    await job_repo.update_status(job_id, "READY_FOR_ANNOTATION")
                    await session.commit()
                return {"segments_detected": 0, "confidence": 0}
            
            # Crop segments from the original video
            logger.info(f"Cropping {len(segments)} segments for job {job_id}")
            cropped_segments = await self._crop_segments(video_path, job_id, segments)
            
            # Validate that at least some segments were cropped successfully
            successful_crops = [p for p in cropped_segments if p is not None]
            if not successful_crops:
                raise ProcessingError(f"All {len(segments)} segments failed to crop")
            
            failed_count = len(cropped_segments) - len(successful_crops)
            if failed_count > 0:
                logger.warning(f"{failed_count}/{len(segments)} segments failed to crop for job {job_id}")
            
            # Store segments in database with cropped video paths
            async with async_session() as session:
                segment_repo = SegmentRepository(session)
                db_segments = []
                for i, (segment, cropped_path) in enumerate(zip(segments, cropped_segments)):
                    db_segment = PipelineSegment(
                        job_id=job_id,
                        segment_index=i,
                        bbox_data=segment.bbox_data if hasattr(segment, 'bbox_data') else None,
                        jbi_start=segment.start_time if hasattr(segment, 'start_time') else None,
                        jbi_end=segment.end_time if hasattr(segment, 'end_time') else None,
                        cropped_video_path=cropped_path
                    )
                    db_segments.append(db_segment)
                await segment_repo.create_many(db_segments)
                await session.commit()
            
            # Queue next stage
            await self._queue_next_stage(job_id, segments)
            
            avg_confidence = sum(s.confidence for s in segments) / len(segments) if segments else 0
            
            return {
                "segments_detected": len(segments),
                "confidence": avg_confidence
            }
        
        except Exception as e:
            # Update job status to FAILED on error
            logger.error(f"Detection failed for job {job_id}: {e}")
            async with async_session() as session:
                job_repo = JobRepository(session)
                await job_repo.update_status(job_id, "FAILED", error_message=str(e))
                await session.commit()
            # Re-raise to trigger retry mechanism
            raise
            
        finally:
            # Cleanup temp file
            if temp_video and temp_video.exists():
                try:
                    temp_video.unlink()
                except OSError:
                    pass
    
    async def _run_detection(self, video_path: str, job_id: UUID):
        """Run detection on video with transcoding if needed."""
        input_path = Path(video_path)
        transcoded_path: Optional[Path] = None
        
        try:
            # Try to detect video codec
            codec_info = await self._get_video_codec(input_path)
            
            if codec_info and codec_info.get("codec_name") in ["av1", "hevc", "vp9"]:
                # Transcode to H.264 for compatibility
                logger.info(f"Detected {codec_info.get('codec_name')} codec, transcoding to H.264")
                transcoded_path = await self._transcode_to_h264(input_path, job_id)
                video_path_to_use = str(transcoded_path)
            else:
                video_path_to_use = str(input_path)
            
            # Run detection
            jbi_segments = await self.detector.detect(Path(video_path_to_use))
            return jbi_segments
            
        finally:
            # Clean up transcoded file
            if transcoded_path and transcoded_path.exists():
                try:
                    transcoded_path.unlink()
                except OSError:
                    pass
    
    async def _get_video_codec(self, video_path: Path) -> dict:
        """
        Get video codec information using ffprobe.
        
        Returns:
            Dict with codec_name, width, height, etc.
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height",
            "-of", "json",
            str(video_path)
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                data = json.loads(stdout.decode())
                streams = data.get("streams", [])
                if streams:
                    return streams[0]
            
            return {}
            
        except Exception as e:
            logger.warning(f"Could not detect video codec: {e}")
            return {}
    
    async def _transcode_to_h264(self, input_path: Path, job_id: UUID) -> Path:
        """
        Transcode video to H.264 for compatibility.
        
        Args:
            input_path: Path to input video (may be AV1 or other codec)
            job_id: Job ID for temp file naming
            
        Returns:
            Path to transcoded H.264 video
        """
        suffix = input_path.suffix
        temp_output = Path(tempfile.gettempdir()) / f"transcoded_{job_id}{suffix}"
        
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output if exists
            "-i", str(input_path),
            "-c:v", "libx264",
            "-crf", "18",
            "-c:a", "copy",
            "-preset", "medium",
            "-movflags", "+faststart",
            "-hide_banner",
            "-loglevel", "error",  # Reduce verbosity
            str(temp_output)
        ]
        
        try:
            logger.info(f"Transcoding video to H.264 for job {job_id}")
            
            # Run ffmpeg in subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"FFmpeg transcoding failed: {error_msg}")
                raise ProcessingError(f"Video transcoding failed: {error_msg}")
            
            logger.info(f"Transcoding complete: {temp_output}")
            return temp_output
            
        except Exception as e:
            # Clean up temp file if created
            if temp_output.exists():
                try:
                    temp_output.unlink()
                except OSError:
                    pass
            raise
    
    async def _crop_segments(
        self, 
        video_path: str, 
        job_id: UUID, 
        segments: list
    ) -> list:
        """
        Crop segments from the original video.
        
        Args:
            video_path: Path to original video
            job_id: Job ID for output naming
            segments: List of detected segments with bbox and timestamps
            
        Returns:
            List of cropped video file paths
        """
        import os
        
        # Create output directory for cropped segments
        output_dir = Path(f"storage/outputs/{job_id}/segments")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cropped_paths = []
        
        for i, segment in enumerate(segments):
            try:
                start_time = getattr(segment, 'start_time', 0)
                end_time = getattr(segment, 'end_time', 0)
                bbox = getattr(segment, 'bbox_data', None)
                
                # Output file path
                output_path = output_dir / f"segment_{i:04d}.mp4"
                
                # Build ffmpeg command for cropping
                # First extract the time segment, then apply bbox crop if available
                duration = end_time - start_time
                
                if bbox and isinstance(bbox, dict):
                    # bbox format: {"x": ..., "y": ..., "width": ..., "height": ...}
                    x = bbox.get("x", 0)
                    y = bbox.get("y", 0)
                    w = bbox.get("width", 0)
                    h = bbox.get("height", 0)
                    # Ensure even dimensions for x264
                    w = w - (w % 2)
                    h = h - (h % 2)
                    x = x - (x % 2)
                    y = y - (y % 2)
                    
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-ss", str(start_time),
                        "-t", str(duration),
                        "-i", video_path,
                        "-vf", f"crop={w}:{h}:{x}:{y}",
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        "-c:a", "aac",
                        "-hide_banner",
                        "-loglevel", "error",
                        str(output_path)
                    ]
                else:
                    # No bbox, just extract time segment
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-ss", str(start_time),
                        "-t", str(duration),
                        "-i", video_path,
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        "-c:a", "aac",
                        "-hide_banner",
                        "-loglevel", "error",
                        str(output_path)
                    ]
                
                # Run ffmpeg
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logger.error(f"Failed to crop segment {i}: {error_msg}")
                    cropped_paths.append(None)
                else:
                    logger.info(f"Cropped segment {i}: {output_path}")
                    cropped_paths.append(str(output_path))
                    
            except Exception as e:
                logger.error(f"Error cropping segment {i}: {e}")
                cropped_paths.append(None)
        
        return cropped_paths
    
    async def _queue_next_stage(self, job_id: UUID, segments):
        """Queue ASR stage after detection."""
        async with async_session() as session:
            await queue_service.enqueue(
                queue_name="asr",
                payload={
                    "job_id": str(job_id),
                    "segment_count": len(segments)
                },
                db=session
            )
            await session.commit()
    
    def _save_temp_video(self, video_data: bytes, job_id: UUID) -> Path:
        """Save video data to temporary file."""
        temp_file = tempfile.NamedTemporaryFile(
            suffix=".mp4",
            delete=False,
            prefix=f"detect_{job_id}_"
        )
        temp_file.write(video_data)
        temp_file.close()
        return Path(temp_file.name)
