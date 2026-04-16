"""Dashboard Router.

Provides aggregated dashboard metrics and statistics.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.api.deps import require_admin
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService, get_dashboard_service


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dashboard statistics",
    responses={
        403: {"description": "Admin access required"},
    },
)
async def get_dashboard(
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
    dashboard_service = get_dashboard_service(db_session)
    data = await dashboard_service.get_dashboard_data()
    return DashboardResponse(**data)
