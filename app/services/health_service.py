"""Health check service for system monitoring."""

import shutil
import logging
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import InMemoryCache
from app.db.models.pipeline import PipelineJob


logger = logging.getLogger(__name__)

# 30-second cache for health checks
health_check_cache = InMemoryCache(default_ttl=30.0)


class HealthService:
    """Service for system health checks."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_system_health(self) -> Dict[str, Any]:
        """
        Get comprehensive system health status.
        
        Returns:
            Dict with health status of all components
        """
        # Check cache first
        cached = health_check_cache.get("system_health")
        if cached:
            return cached
        
        # Run all health checks
        health = {
            "api": "healthy",
            "database": await self._check_database(),
            "minio": await self._check_minio(),
            "yolo_model": await self._check_yolo_model(),
            "gpu_available": await self._check_gpu(),
            "disk_space": self._check_disk_space(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Cache result
        health_check_cache.set("system_health", health)
        
        return health
    
    async def _check_database(self) -> str:
        """Check database connectivity."""
        try:
            await self.db.execute(select(func.count(PipelineJob.id)))
            return "connected"
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            return "disconnected"
    
    async def _check_minio(self) -> str:
        """Check MinIO connectivity."""
        try:
            from app.services.minio_service import get_minio_service
            minio = get_minio_service()
            # Try to list buckets as connectivity check
            buckets = await minio.client.list_buckets()
            return "connected"
        except Exception as e:
            logger.warning(f"MinIO health check failed: {e}")
            return "disconnected"
    
    async def _check_yolo_model(self) -> str:
        """Check if YOLO model is loaded."""
        try:
            from app.pipeline.models.detector import get_detector
            detector = get_detector()
            # Check if model is loaded by checking model attribute
            if hasattr(detector, 'model') and detector.model is not None:
                return "loaded"
            return "not_loaded"
        except Exception as e:
            logger.warning(f"YOLO model health check failed: {e}")
            return "not_loaded"
    
    async def _check_gpu(self) -> bool:
        """Check if GPU is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False
    
    def _check_disk_space(self) -> str:
        """Check disk space status."""
        try:
            usage = shutil.disk_usage("/")
            percent_used = (usage.used / usage.total) * 100
            
            if percent_used > 90:
                return "critical"
            elif percent_used > 75:
                return "low"
            else:
                return "OK"
        except Exception as e:
            logger.warning(f"Disk space check failed: {e}")
            return "unknown"


# Factory function
def get_health_service(db: AsyncSession) -> HealthService:
    return HealthService(db)
