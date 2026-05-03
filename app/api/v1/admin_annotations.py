"""Admin endpoints for annotation management."""
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, CurrentUser
from app.db.session import get_db
from app.db.models.annotation import AnnotationQueue
from app.db.models.pipeline import PipelineSegment
from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.segment_repository import SegmentRepository

router = APIRouter(prefix="/admin/annotations", tags=["admin-annotations"])


@router.post(
    "/assign-segments",
    summary="Assign segments to annotator (Admin)",
    description="Manually assign pipeline segments to an annotator for annotation."
)
async def assign_segments_to_annotator(
    segment_ids: List[UUID],
    annotator_id: UUID,
    priority: int = Query(0, ge=0, le=10),
    due_days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Assign one or more segments to an annotator.
    
    This creates annotation_queue entries for segments that are ready
    for annotation (after pipeline processing is complete).
    
    - **segment_ids**: List of pipeline segment UUIDs to assign
    - **annotator_id**: UUID of the annotator to assign to
    - **priority**: Priority level (0-10, higher = more important)
    - **due_days**: Number of days until due date
    """
    queue_repo = AnnotationQueueRepository(db)
    segment_repo = SegmentRepository(db)
    
    assigned = []
    skipped = []
    errors = []
    
    for segment_id in segment_ids:
        try:
            # Check if segment exists
            segment = await segment_repo.get_by_id(segment_id)
            if not segment:
                errors.append({"segment_id": str(segment_id), "error": "Segment not found"})
                continue
            
            # Check if already in queue
            existing = await queue_repo.get_by_segment(segment_id)
            if existing:
                skipped.append({
                    "segment_id": str(segment_id),
                    "reason": "Already in queue",
                    "current_annotator": str(existing.annotator_id),
                    "status": existing.status
                })
                continue
            
            # Create queue entry
            queue_entry = AnnotationQueue(
                segment_id=segment_id,
                annotator_id=annotator_id,
                status=AnnotationQueue.STATUS_ASSIGNED,
                priority=priority,
                assigned_at=datetime.utcnow(),
                due_date=datetime.utcnow() + timedelta(days=due_days)
            )
            
            db.add(queue_entry)
            await db.flush()
            await db.refresh(queue_entry)
            
            assigned.append({
                "queue_id": str(queue_entry.id),
                "segment_id": str(segment_id),
                "annotator_id": str(annotator_id),
                "status": AnnotationQueue.STATUS_ASSIGNED
            })
            
        except Exception as e:
            errors.append({"segment_id": str(segment_id), "error": str(e)})
    
    await db.commit()
    
    return {
        "success": True,
        "summary": {
            "total_requested": len(segment_ids),
            "assigned": len(assigned),
            "skipped": len(skipped),
            "errors": len(errors)
        },
        "assigned": assigned,
        "skipped": skipped,
        "errors": errors
    }


@router.post(
    "/assign-job",
    summary="Assign job to annotator (Admin)",
    description="Assign all unassigned segments of a pipeline job to an annotator."
)
async def assign_job_to_annotator(
    job_id: UUID,
    annotator_id: UUID,
    priority: int = Query(0, ge=0, le=10),
    due_days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Assign an entire job to an annotator.
    
    Finds all segments belonging to the job that are not yet assigned
    and assigns them to the specified annotator.
    """
    from sqlalchemy import select, not_, exists
    
    queue_repo = AnnotationQueueRepository(db)
    
    # Query segments that belong to the job and don't have a queue entry yet
    query = select(PipelineSegment).where(
        PipelineSegment.job_id == job_id,
        not_(
            exists().where(
                AnnotationQueue.segment_id == PipelineSegment.id
            )
        )
    )
    
    result = await db.execute(query)
    unassigned_segments = result.scalars().all()
    
    if not unassigned_segments:
        return {
            "success": False,
            "message": "No unassigned segments found for this job.",
            "assigned_count": 0
        }
    
    assigned = []
    
    for segment in unassigned_segments:
        queue_entry = AnnotationQueue(
            segment_id=segment.id,
            annotator_id=annotator_id,
            status=AnnotationQueue.STATUS_ASSIGNED,
            priority=priority,
            assigned_at=datetime.utcnow(),
            due_date=datetime.utcnow() + timedelta(days=due_days)
        )
        db.add(queue_entry)
        assigned.append(str(segment.id))
        
    await db.commit()
    
    return {
        "success": True,
        "message": f"Successfully assigned {len(assigned)} segments to annotator.",
        "assigned_count": len(assigned),
        "segment_ids": assigned
    }


@router.get(
    "/unassigned-segments",
    summary="Get unassigned segments (Admin)",
    description="Get pipeline segments that are not yet in the annotation queue."
)
async def get_unassigned_segments(
    job_id: Optional[UUID] = None,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Get segments that have completed pipeline processing but are not
    yet assigned to any annotator (not in annotation_queue).
    
    These are segments ready to be assigned for annotation.
    """
    from sqlalchemy import select, not_, exists
    
    # Query segments that don't have a queue entry
    query = select(PipelineSegment).where(
        not_(
            exists().where(
                AnnotationQueue.segment_id == PipelineSegment.id
            )
        )
    )
    
    if job_id:
        query = query.where(PipelineSegment.job_id == job_id)
    
    query = query.limit(limit)
    
    result = await db.execute(query)
    segments = result.scalars().all()
    
    return {
        "total_unassigned": len(segments),
        "segments": [
            {
                "segment_id": str(seg.id),
                "job_id": str(seg.job_id),
                "segment_index": seg.segment_index,
                "cropped_video_path": seg.cropped_video_path,
                "asr_text": seg.asr_text,
                "asr_confidence": seg.asr_confidence
            }
            for seg in segments
        ]
    }


@router.get(
    "/queue-status",
    summary="Get annotation queue status (Admin)",
    description="Overview of annotation queue status across all annotators."
)
async def get_queue_status(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin)
):
    """Get statistics about the annotation queue."""
    from sqlalchemy import func, select
    from app.db.models.auth import User
    
    # Count by status
    status_counts = await db.execute(
        select(AnnotationQueue.status, func.count(AnnotationQueue.id))
        .group_by(AnnotationQueue.status)
    )
    
    # Count by annotator
    annotator_counts = await db.execute(
        select(
            User.email,
            AnnotationQueue.status,
            func.count(AnnotationQueue.id)
        )
        .join(AnnotationQueue, AnnotationQueue.annotator_id == User.id)
        .group_by(User.email, AnnotationQueue.status)
    )
    
    return {
        "by_status": {row[0]: row[1] for row in status_counts.fetchall()},
        "by_annotator": [
            {
                "annotator_email": row[0],
                "status": row[1],
                "count": row[2]
            }
            for row in annotator_counts.fetchall()
        ],
        "total_in_queue": sum(row[1] for row in status_counts.fetchall())
    }
