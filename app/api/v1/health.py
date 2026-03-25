"""Health check endpoints."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.health_service import get_health_service, HealthService
from app.schemas.job import HealthResponse, ErrorResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    tags=["Health"],
    responses={
        200: {"model": HealthResponse},
        503: {"model": ErrorResponse, "description": "Service unhealthy"}
    }
)
async def health_check(
    db: AsyncSession = Depends(get_db)
):
    """
    Get system health status.
    
    Returns health of all system components:
    - api: API server status
    - database: Database connectivity
    - minio: Object storage connectivity
    - yolo_model: ML model loaded status
    - gpu_available: GPU availability
    - disk_space: Disk space status
    
    Results are cached for 30 seconds.
    """
    health_service = get_health_service(db)
    health = await health_service.get_system_health()
    
    # Determine overall status
    is_healthy = (
        health["database"] == "connected" and
        health["minio"] == "connected"
    )
    
    response_data = {
        "status": "healthy" if is_healthy else "degraded",
        "database": health["database"],
        "minio": health["minio"],
        "yolo_model": health["yolo_model"],
        "gpu_available": health["gpu_available"],
        "disk_space": health["disk_space"]
    }
    
    # Return 503 if critical services are down
    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response_data
        )
    
    return response_data


@router.get(
    "/health/ready",
    summary="Readiness probe",
    tags=["Health"],
)
async def readiness_probe(
    db: AsyncSession = Depends(get_db)
):
    """
    Kubernetes-style readiness probe.
    
    Returns 200 when the service is ready to accept traffic.
    """
    try:
        health_service = get_health_service(db)
        health = await health_service.get_system_health()
        
        if health["database"] == "connected":
            return {"status": "ready"}
        else:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "reason": "database_unavailable"}
            )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "reason": "error"}
        )


@router.get(
    "/health/live",
    summary="Liveness probe",
    tags=["Health"],
)
async def liveness_probe():
    """
    Kubernetes-style liveness probe.
    
    Returns 200 if the service is running (even if degraded).
    """
    return {"status": "alive"}
