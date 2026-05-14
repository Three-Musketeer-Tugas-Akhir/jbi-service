"""Dashboard Router.

Provides aggregated dashboard metrics and statistics.
"""
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.api.deps import require_admin, require_annotator_or_curator, get_current_user
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService, get_dashboard_service
from app.services.my_dashboard_service import get_annotator_dashboard, get_curator_dashboard


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dashboard statistics (admin only)",
    responses={
        403: {"description": "Admin access required"},
    },
)
async def get_dashboard(
    dataset_id: Optional[str] = Query(None, description="Filter by dataset ID"),
    current_user=Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get aggregated dashboard data for the admin panel.

    Returns:
    - Top-level statistics cards (total videos, chunks, annotations, export ready)
    - Pipeline progress tracker across all stages
    - Conversion rates per stage
    - Recent system activities from audit logs
    """
    dataset_uuid = None
    if dataset_id:
        try:
            dataset_uuid = _uuid.UUID(dataset_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid dataset_id: {dataset_id}")

    dashboard_service = get_dashboard_service(db_session)
    data = await dashboard_service.get_dashboard_data(dataset_id=dataset_uuid)
    return DashboardResponse(**data)


@router.get(
    "/my",
    status_code=status.HTTP_200_OK,
    summary="Get personalized dashboard for annotator or curator",
    responses={
        403: {"description": "Annotator or curator access required"},
    },
)
async def get_my_dashboard(
    dataset_id: Optional[str] = Query(None, description="Filter by dataset ID"),
    current_user=Depends(require_annotator_or_curator),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get personalized dashboard data based on the current user's role.

    - **annotator**: Returns assigned jobs with per-job progress (segments completed/total).
    - **curator**: Returns all jobs in curation pipeline (ANNOTATED → READY_TO_EXPORT).
    """
    dataset_uuid = None
    if dataset_id:
        try:
            dataset_uuid = _uuid.UUID(dataset_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid dataset_id: {dataset_id}")

    role = current_user.role
    if role == "annotator":
        return await get_annotator_dashboard(db_session, current_user.id, dataset_id=dataset_uuid)
    elif role == "curator":
        return await get_curator_dashboard(db_session, current_user.id, dataset_id=dataset_uuid)
    else:
        # admin accessing /my — return a simple redirect hint
        return {"role": "admin", "message": "Use /dashboard for admin data"}
