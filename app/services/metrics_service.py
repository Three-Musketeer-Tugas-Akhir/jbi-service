"""Metrics aggregation service for system monitoring."""

import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any, List

from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineJob, QueueJob


logger = logging.getLogger(__name__)


class MetricsService:
    """Service for aggregating system metrics."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get aggregated system metrics.
        
        Returns:
            Dict with various system metrics
        """
        today = datetime.utcnow().date()
        
        # Jobs completed today
        completed_today = await self._count_jobs_by_status(
            status="READY_FOR_ANNOTATION",
            date=today
        )
        
        # Jobs failed today
        failed_today = await self._count_jobs_by_status(
            status="FAILED",
            date=today
        )
        
        # Jobs cancelled today
        cancelled_today = await self._count_jobs_by_status(
            status="CANCELLED",
            date=today
        )
        
        # Average processing time
        avg_processing_time = await self._get_average_processing_time()
        
        # Queue depth by stage
        queue_depth = await self._get_queue_depth_by_stage()
        
        # GPU utilization (if available)
        gpu_util = await self._get_gpu_utilization()
        
        return {
            "jobs_completed_today": completed_today,
            "jobs_failed_today": failed_today,
            "jobs_cancelled_today": cancelled_today,
            "average_processing_time_seconds": avg_processing_time,
            "queue_depth_by_stage": queue_depth,
            "gpu_utilization_percent": gpu_util,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _count_jobs_by_status(self, status: str, date: date) -> int:
        """Count jobs by status for a specific date."""
        try:
            # Use PostgreSQL date casting
            result = await self.db.execute(
                select(func.count(PipelineJob.id))
                .where(
                    PipelineJob.status == status,
                    func.date(PipelineJob.created_at) == date
                )
            )
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"Error counting jobs: {e}")
            return 0
    
    async def _get_average_processing_time(self) -> float:
        """Get average processing time for completed jobs (last 24 hours)."""
        try:
            yesterday = datetime.utcnow() - timedelta(hours=24)
            
            result = await self.db.execute(
                select(
                    func.avg(
                        func.extract('epoch', PipelineJob.completed_at) - 
                        func.extract('epoch', PipelineJob.created_at)
                    )
                )
                .where(
                    PipelineJob.status == "READY_FOR_ANNOTATION",
                    PipelineJob.completed_at.is_not(None),
                    PipelineJob.completed_at >= yesterday
                )
            )
            avg_seconds = result.scalar()
            return round(avg_seconds, 2) if avg_seconds else 0.0
        except Exception as e:
            logger.error(f"Error calculating avg processing time: {e}")
            return 0.0
    
    async def _get_queue_depth_by_stage(self) -> Dict[str, int]:
        """Get queue depth by processing stage."""
        try:
            result = await self.db.execute(
                select(
                    PipelineJob.current_stage,
                    func.count(PipelineJob.id)
                )
                .where(PipelineJob.status.in_(["QUEUED", "PROCESSING"]))
                .group_by(PipelineJob.current_stage)
            )
            
            depth = {}
            for row in result.all():
                stage, count = row
                depth[stage or "unknown"] = count
            
            return depth
        except Exception as e:
            logger.error(f"Error getting queue depth: {e}")
            return {}
    
    async def _get_gpu_utilization(self) -> float:
        """Get current GPU utilization."""
        try:
            import torch
            if torch.cuda.is_available():
                # Get utilization for GPU 0
                util = torch.cuda.utilization(0)
                return float(util)
        except Exception:
            pass
        return 0.0
    
    async def get_failed_jobs(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get list of failed jobs for admin review.
        
        Args:
            limit: Max jobs to return
            offset: Pagination offset
            
        Returns:
            Dict with failed jobs and pagination info
        """
        try:
            # Get total count
            count_result = await self.db.execute(
                select(func.count(PipelineJob.id))
                .where(PipelineJob.status == "FAILED")
            )
            total = count_result.scalar() or 0
            
            # Get failed jobs
            result = await self.db.execute(
                select(PipelineJob)
                .where(PipelineJob.status == "FAILED")
                .order_by(PipelineJob.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            
            jobs = result.scalars().all()
            
            failed_jobs = []
            for job in jobs:
                # Get retry count from queue logs
                retry_count = await self._get_retry_count(job.id)
                
                failed_jobs.append({
                    "job_id": str(job.id),
                    "error_message": job.error_message or "Unknown error",
                    "failed_at": job.updated_at.isoformat() if job.updated_at else None,
                    "stage": job.current_stage or "unknown",
                    "retry_count": retry_count,
                    "original_filename": job.original_filename
                })
            
            return {
                "jobs": failed_jobs,
                "total": total,
                "limit": limit,
                "offset": offset
            }
        except Exception as e:
            logger.error(f"Error getting failed jobs: {e}")
            return {
                "jobs": [],
                "total": 0,
                "limit": limit,
                "offset": offset
            }
    
    async def _get_retry_count(self, job_id) -> int:
        """Get retry count for a job from queue jobs."""
        try:
            # Count queue job attempts for this pipeline job
            result = await self.db.execute(
                select(func.count(QueueJob.id))
                .where(
                    QueueJob.payload["job_id"].astext == str(job_id),
                    QueueJob.attempts > 0
                )
            )
            return result.scalar() or 0
        except Exception:
            return 0


# Factory function
def get_metrics_service(db: AsyncSession) -> MetricsService:
    return MetricsService(db)
