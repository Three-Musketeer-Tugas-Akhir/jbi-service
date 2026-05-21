"""
Admin Audit Router.

Administrative endpoints for audit log management.
All endpoints require admin role.
"""

from datetime import datetime, timedelta
from io import StringIO
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.api.deps import require_admin, CurrentUser
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.audit import (
    AuditLogListResponse,
    AuditLogDetailResponse,
    AuditLogResponse,
    AuditLogActorResponse,
    AuditLogResourceResponse,
    AuditStatsSummary,
    ActionCount,
    DailyActivity,
    UserActivitySummary,
    ResourceActivitySummary,
    get_action_label,
)

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])


# ============================================================================
# Module → Actions Mapping
# ============================================================================

MODULE_ACTIONS = {
    "pipeline": [
        "job.created", "job.cancelled", "job.deleted", "job.status_changed",
        "pipeline.stage_started", "pipeline.stage_completed", "pipeline.stage_failed",
    ],
    "classification": [
        "classification.updated",
    ],
    "voice_annotation": [
        "voice_annotation.updated", "asr_review.submitted", "asr_review.corrected",
    ],
    "jbi_annotation": [
        "jbi_annotation.draft_saved", "jbi_annotation.edit_created", "jbi_annotation.reset",
        "annotation.submitted", "annotation.approved", "annotation.rejected",
    ],
    "normalization": [
        "normalization.applied",
    ],
    "curation": [
        "curation.approved", "curation.normalized",
    ],
}

# ============================================================================
# Helper Functions
# ============================================================================

def _get_ip_address(request: Request) -> Optional[str]:
    """Extract IP address from request."""
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    elif request.client:
        return request.client.host
    return None


def _format_audit_log_response(log) -> AuditLogResponse:
    """Format audit log for response."""
    return AuditLogResponse(
        id=log.id,
        timestamp=log.timestamp,
        actor=AuditLogActorResponse(
            id=log.actor.id if log.actor else None,
            email=log.actor.email if log.actor else None
        ) if log.actor else None,
        action=log.action,
        action_label=get_action_label(log.action),
        resource=AuditLogResourceResponse(
            type=log.resource_type,
            id=log.resource_id
        ),
        details=log.details or {},
        ip_address=log.ip_address
    )


def _format_audit_log_detail_response(log) -> AuditLogDetailResponse:
    """Format audit log with full details for response."""
    return AuditLogDetailResponse(
        id=log.id,
        timestamp=log.timestamp,
        actor=AuditLogActorResponse(
            id=log.actor.id if log.actor else None,
            email=log.actor.email if log.actor else None
        ) if log.actor else None,
        action=log.action,
        action_label=get_action_label(log.action),
        resource=AuditLogResourceResponse(
            type=log.resource_type,
            id=log.resource_id
        ),
        details=log.details or {},
        ip_address=log.ip_address,
        user_agent=log.details.get("user_agent") if log.details else None
    )


# ============================================================================
# List Audit Logs Endpoint
# ============================================================================

@router.get(
    "/logs",
    response_model=AuditLogListResponse,
    responses={
        403: {"description": "Admin access required"},
        422: {"description": "Invalid query parameters"},
    },
)
async def list_audit_logs(
    start_date: Optional[datetime] = Query(None, description="Filter by start date (ISO8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date (ISO8601)"),
    actor_id: Optional[UUID] = Query(None, description="Filter by user who performed action"),
    action: Optional[str] = Query(None, description="Filter by action type (e.g., 'user.created')"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type (e.g., 'job', 'user')"),
    resource_id: Optional[UUID] = Query(None, description="Filter by specific resource ID"),
    ip_address: Optional[str] = Query(None, description="Filter by IP address"),
    module: Optional[str] = Query(None, description="Filter by feature module (pipeline, classification, voice_annotation, jbi_annotation, normalization, curation)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    List audit logs with filtering (Admin only).
    
    Supports filtering by date range, actor, action type, resource type, and IP address.
    Results are sorted by timestamp descending (most recent first).
    """
    repository = AuditLogRepository(db_session)
    
    # Calculate offset
    offset = (page - 1) * page_size
    
    # Resolve module filter to actions list
    actions_filter = MODULE_ACTIONS.get(module) if module else None

    # Search with filters
    logs, total = await repository.search_with_filters(
        start_date=start_date,
        end_date=end_date,
        actor_id=actor_id,
        action=action,
        actions=actions_filter,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        limit=page_size,
        offset=offset
    )
    
    # Format response
    items = [_format_audit_log_response(log) for log in logs]
    pages = (total + page_size - 1) // page_size
    
    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages
    )


# ============================================================================
# Get Single Audit Log Endpoint
# ============================================================================

@router.get(
    "/logs/{log_id}",
    response_model=AuditLogDetailResponse,
    responses={
        403: {"description": "Admin access required"},
        404: {"description": "Audit log not found"},
    },
)
async def get_audit_log(
    log_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get detailed information about a specific audit log entry (Admin only).
    
    Includes full details and any additional metadata stored in the log.
    """
    repository = AuditLogRepository(db_session)
    
    log = await repository.get_by_id(log_id)
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit log not found"
        )
    
    return _format_audit_log_detail_response(log)


# ============================================================================
# Get Audit Statistics Endpoint
# ============================================================================

@router.get(
    "/stats",
    response_model=AuditStatsSummary,
    responses={
        403: {"description": "Admin access required"},
    },
)
async def get_audit_stats(
    start_date: Optional[datetime] = Query(None, description="Statistics period start"),
    end_date: Optional[datetime] = Query(None, description="Statistics period end"),
    days: Optional[int] = Query(None, ge=1, le=365, description="Number of days to look back (alternative to start_date/end_date)"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get audit log statistics summary (Admin only).
    
    Returns:
    - Total log entries in the period
    - Number of unique users who performed actions
    - Top actions with counts
    - Daily activity for the period
    """
    repository = AuditLogRepository(db_session)
    
    # Calculate date range
    if days:
        end_date = end_date or datetime.utcnow()
        start_date = end_date - timedelta(days=days)
    else:
        # Default to last 30 days if no dates provided
        if not start_date and not end_date:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30)
        elif not start_date:
            start_date = end_date - timedelta(days=30)
        elif not end_date:
            end_date = datetime.utcnow()
    
    # Get total count
    logs, total = await repository.search_with_filters(
        start_date=start_date,
        end_date=end_date,
        limit=1,
        offset=0
    )
    
    # Get unique users count
    unique_users = await repository.get_unique_user_count(start_date, end_date)
    
    # Get top actions
    action_counts = await repository.get_stats_by_action(start_date, end_date, limit=10)
    top_actions = [
        ActionCount(action=action, label=get_action_label(action), count=count)
        for action, count in action_counts
    ]
    
    # Get daily activity
    daily_counts = await repository.get_daily_activity(start_date, end_date)
    daily_activity = [
        DailyActivity(date=date, count=count)
        for date, count in daily_counts
    ]
    
    return AuditStatsSummary(
        total_logs=total,
        unique_users=unique_users,
        period_start=start_date,
        period_end=end_date,
        top_actions=top_actions,
        daily_activity=daily_activity
    )


# ============================================================================
# Get User Activity Summary Endpoint
# ============================================================================

@router.get(
    "/users/{user_id}/activity",
    response_model=UserActivitySummary,
    responses={
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user_activity(
    user_id: UUID,
    period_days: int = Query(30, ge=1, le=365, description="Activity period in days"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get activity summary for a specific user (Admin only).
    
    Returns:
    - Total actions in the period
    - Last active timestamp
    - Breakdown of actions by type
    """
    repository = AuditLogRepository(db_session)
    
    summary = await repository.get_user_activity_summary(user_id, period_days)
    
    if not summary.get("email"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    actions_by_type = [
        ActionCount(action=action, label=get_action_label(action), count=count)
        for action, count in summary.get("actions_by_type", [])
    ]
    
    return UserActivitySummary(
        user_id=user_id,
        email=summary["email"],
        total_actions=summary["total_actions"],
        last_active=summary["last_active"],
        actions_by_type=actions_by_type,
        period_days=period_days
    )


# ============================================================================
# Get Resource Activity Summary Endpoint
# ============================================================================

@router.get(
    "/resources/{resource_type}/{resource_id}",
    response_model=ResourceActivitySummary,
    responses={
        403: {"description": "Admin access required"},
    },
)
async def get_resource_activity(
    resource_type: str,
    resource_id: UUID,
    limit: int = Query(50, ge=1, le=100, description="Number of recent actions to include"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get activity history for a specific resource (Admin only).
    
    Returns:
    - Total actions on this resource
    - First created timestamp (if available)
    - Last modified timestamp
    - Recent action history
    """
    repository = AuditLogRepository(db_session)
    
    # Get all logs for this resource
    logs = await repository.list_by_resource(resource_type, resource_id, limit=limit)
    
    if not logs:
        # Return empty summary
        return ResourceActivitySummary(
            resource_type=resource_type,
            resource_id=resource_id,
            total_actions=0,
            created_at=None,
            last_modified=None,
            action_history=[]
        )
    
    # Calculate timestamps
    timestamps = [log.timestamp for log in logs]
    created_at = min(timestamps)
    last_modified = max(timestamps)
    
    # Format action history
    action_history = [_format_audit_log_response(log) for log in logs]
    
    return ResourceActivitySummary(
        resource_type=resource_type,
        resource_id=resource_id,
        total_actions=len(logs),
        created_at=created_at,
        last_modified=last_modified,
        action_history=action_history
    )


# ============================================================================
# Export Audit Logs Endpoint
# ============================================================================

@router.get(
    "/export",
    response_class=PlainTextResponse,
    responses={
        403: {"description": "Admin access required"},
    },
)
async def export_audit_logs(
    format: str = Query("json", pattern="^(json|csv)$", description="Export format: 'json' or 'csv'"),
    start_date: Optional[datetime] = Query(None, description="Export from date"),
    end_date: Optional[datetime] = Query(None, description="Export to date"),
    days: Optional[int] = Query(None, ge=1, le=365, description="Number of days to look back"),
    actor_id: Optional[UUID] = Query(None, description="Filter by actor"),
    action: Optional[str] = Query(None, description="Filter by action"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Export audit logs to JSON or CSV format (Admin only).
    
    Returns the exported data directly in the response body.
    For large exports, this may be slow - consider using date filters.
    
    CSV format includes: timestamp, actor_email, action, resource_type, resource_id, ip_address, details
    JSON format includes full audit log entries with actor and resource details.
    """
    import json
    import csv
    
    repository = AuditLogRepository(db_session)
    
    # Calculate date range
    if days:
        end_date = end_date or datetime.utcnow()
        start_date = end_date - timedelta(days=days)
    
    # Get all matching logs (without pagination for export)
    logs, total = await repository.search_with_filters(
        start_date=start_date,
        end_date=end_date,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        limit=10000,  # Reasonable limit for export
        offset=0
    )
    
    if format == "csv":
        # Generate CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "timestamp", "actor_id", "actor_email", "action", "action_label",
            "resource_type", "resource_id", "ip_address", "details"
        ])
        
        # Write data
        for log in logs:
            writer.writerow([
                log.timestamp.isoformat() if log.timestamp else "",
                str(log.actor_id) if log.actor_id else "",
                log.actor.email if log.actor else "",
                log.action,
                get_action_label(log.action),
                log.resource_type,
                str(log.resource_id) if log.resource_id else "",
                log.ip_address or "",
                json.dumps(log.details) if log.details else "{}"
            ])
        
        content = output.getvalue()
        output.close()
        
        return PlainTextResponse(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    
    else:
        # Generate JSON
        data = []
        for log in logs:
            data.append({
                "id": str(log.id),
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "actor": {
                    "id": str(log.actor.id) if log.actor else None,
                    "email": log.actor.email if log.actor else None
                },
                "action": log.action,
                "action_label": get_action_label(log.action),
                "resource": {
                    "type": log.resource_type,
                    "id": str(log.resource_id) if log.resource_id else None
                },
                "details": log.details or {},
                "ip_address": log.ip_address
            })
        
        content = json.dumps(data, indent=2, default=str)
        
        return PlainTextResponse(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=audit_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"}
        )


# ============================================================================
# Get Available Filters Endpoint
# ============================================================================

@router.get(
    "/filters",
    responses={
        403: {"description": "Admin access required"},
    },
)
async def get_available_filters(
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get available filter values for audit log filtering (Admin only).
    
    Returns:
    - List of unique action types
    - List of unique resource types
    - Action label mappings
    """
    repository = AuditLogRepository(db_session)
    
    actions = await repository.get_unique_actions()
    resource_types = await repository.get_unique_resource_types()
    
    action_mappings = [
        {"action": action, "label": get_action_label(action)}
        for action in actions
    ]
    
    return {
        "actions": action_mappings,
        "resource_types": resource_types
    }
