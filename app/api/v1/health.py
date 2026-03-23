import shutil
import logging

import torch
from fastapi import APIRouter

from app.core.config import settings
from app.schemas import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Minimum free disk space before reporting unhealthy (1 GB)
MIN_DISK_FREE_GB = 1.0


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check service health: model, GPU, and disk status."""
    model_loaded = _check_model_loaded()
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    disk_free_gb = _check_disk_free()

    status = _determine_status(model_loaded, gpu_available, disk_free_gb)

    return HealthResponse(
        status=status,
        model_loaded=model_loaded,
        gpu_available=gpu_available,
        gpu_name=gpu_name,
        disk_free_gb=disk_free_gb,
    )


def _check_model_loaded() -> bool:
    """Check if the detector service has been initialized with a model."""
    try:
        from app.services.detector import _detector
        return _detector is not None
    except Exception:
        return False


def _check_disk_free() -> float:
    """Get free disk space in GB on the storage partition."""
    try:
        usage = shutil.disk_usage(settings.output_dir)
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        logger.warning("Could not read disk usage for %s", settings.output_dir)
        return 0.0


def _determine_status(
    model_loaded: bool,
    gpu_available: bool,
    disk_free_gb: float,
) -> str:
    """Determine overall health status."""
    if not model_loaded:
        return "unhealthy"
    if disk_free_gb < MIN_DISK_FREE_GB:
        return "unhealthy"
    if settings.processing_mode.lower() == "gpu" and not gpu_available:
        return "degraded"
    return "healthy"
