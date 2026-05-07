"""Dataset API endpoints for project/dataset management."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.auth import User
from app.api.deps import get_current_user
from app.repositories.dataset_repository import DatasetRepository, get_dataset_repository
from app.services.dataset_service import DatasetService, get_dataset_service
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["datasets"])


# ── Schemas (inline to avoid circular imports) ───────────────────────────

class DatasetCreateRequest:
    """Request to create a dataset."""
    pass  # We'll use Form params instead


from pydantic import BaseModel, Field


class DatasetCreateBody(BaseModel):
    """Request body for creating a dataset."""
    name: str = Field(..., min_length=1, max_length=255, description="Dataset name")
    description: Optional[str] = Field(None, max_length=1000, description="Optional description")


class DatasetResponse(BaseModel):
    """Dataset response."""
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class DatasetListResponse(BaseModel):
    """Paginated dataset list response."""
    items: list[DatasetResponse]
    total: int
    limit: int
    offset: int


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new dataset",
)
async def create_dataset(
    body: DatasetCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dataset_repo: DatasetRepository = Depends(get_dataset_repository),
):
    """Create a new dataset/project.
    
    Examples: "iNews 2025", "TVRI 2024"
    """
    try:
        service = get_dataset_service(db, dataset_repo)
        dataset = await service.create_dataset(
            name=body.name,
            description=body.description,
            created_by=current_user.id
        )
        
        logger.info("Dataset created: id=%s, name=%s, user=%s", dataset.id, dataset.name, current_user.id)
        
        return DatasetResponse(
            id=str(dataset.id),
            name=dataset.name,
            description=dataset.description,
            created_at=dataset.created_at.isoformat() if dataset.created_at else None,
            updated_at=dataset.updated_at.isoformat() if dataset.updated_at else None,
        )
    except Exception as e:
        logger.error("Failed to create dataset: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset: {str(e)}"
        )


@router.get(
    "",
    response_model=DatasetListResponse,
    summary="List all datasets",
)
async def list_datasets(
    limit: int = Query(100, ge=1, le=500, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dataset_repo: DatasetRepository = Depends(get_dataset_repository),
):
    """List all available datasets.
    
    Sorted by creation time (newest first).
    """
    try:
        service = get_dataset_service(db, dataset_repo)
        result = await service.list_datasets(limit=limit, offset=offset)
        
        items = [
            DatasetResponse(
                id=str(d.id),
                name=d.name,
                description=d.description,
                created_at=d.created_at.isoformat() if d.created_at else None,
                updated_at=d.updated_at.isoformat() if d.updated_at else None,
            )
            for d in result["items"]
        ]
        
        return DatasetListResponse(
            items=items,
            total=result["total"],
            limit=result["limit"],
            offset=result["offset"],
        )
    except Exception as e:
        logger.error("Failed to list datasets: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list datasets: {str(e)}"
        )


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Get a single dataset",
)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dataset_repo: DatasetRepository = Depends(get_dataset_repository),
):
    """Get a single dataset by ID."""
    service = get_dataset_service(db, dataset_repo)
    dataset = await service.get_dataset(dataset_id)
    
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_id}' not found"
        )
    
    return DatasetResponse(
        id=str(dataset.id),
        name=dataset.name,
        description=d.description,
        created_at=dataset.created_at.isoformat() if dataset.created_at else None,
        updated_at=dataset.updated_at.isoformat() if dataset.updated_at else None,
    )
