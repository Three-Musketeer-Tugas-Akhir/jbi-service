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
                errors.append({"segment_id": str(segment_id), "error": "Segment tidak ditemukan"})
                continue
            
            # Check if already in queue
            existing = await queue_repo.get_by_segment(segment_id)
            if existing:
                skipped.append({
                    "segment_id": str(segment_id),
                    "reason": "Sudah ada di antrean",
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
            "message": "Tidak ada segment yang belum di-assign untuk job ini.",
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
        "message": f"Berhasil meng-assign {len(assigned)} segment ke annotator.",
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


@router.post(
    "/reassign-job",
    summary="Reassign a job to a different annotator (Admin)",
    description="Reassign all segments of a pipeline job to a new annotator without resetting progress."
)
async def reassign_job_to_annotator(
    job_id: UUID,
    annotator_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Reassign an entire job to a different annotator.
    
    Updates the annotator_id on existing annotation_queue entries for all
    segments belonging to the job. Does NOT modify AnnotationEdit records,
    so existing progress (drafts, corrections) is preserved.
    
    - **job_id**: UUID of the pipeline job to reassign
    - **annotator_id**: UUID of the new annotator
    """
    from app.db.models.auth import User
    from app.db.models.pipeline import PipelineJob, JobStatus
    
    # Verify job exists and is ready for annotation
    job = await db.get(PipelineJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    
    if job.status != JobStatus.READY_FOR_ANNOTATION:
        raise HTTPException(
            status_code=400,
            detail=f"Job harus berstatus '{JobStatus.READY_FOR_ANNOTATION}' untuk di-reassign. Status saat ini: {job.status}"
        )
    
    # Verify annotator exists and has annotator role
    annotator = await db.get(User, annotator_id)
    if not annotator:
        raise HTTPException(status_code=404, detail="Annotator tidak ditemukan")
    
    if not annotator.has_any_role(["annotator", "admin"]):
        raise HTTPException(status_code=400, detail="User harus berperan sebagai annotator atau admin")
    
    # Find all queue entries for this job's segments
    queue_repo = AnnotationQueueRepository(db)
    queue_entries = await queue_repo.get_by_job_id(job_id)
    
    if not queue_entries:
        raise HTTPException(
            status_code=400,
            detail="Tidak ada segment yang di-assign untuk job ini. Gunakan /assign-job untuk assign terlebih dahulu."
        )
    
    reassigned = []
    for entry in queue_entries:
        old_annotator_id = entry.annotator_id
        entry.annotator_id = annotator_id
        entry.assigned_at = datetime.utcnow()
        reassigned.append({
            "queue_id": str(entry.id),
            "segment_id": str(entry.segment_id),
            "old_annotator_id": str(old_annotator_id),
            "new_annotator_id": str(annotator_id),
            "status": entry.status
        })
    
    await db.commit()
    
    return {
        "success": True,
        "message": f"Berhasil meng-reassign {len(reassigned)} segment ke annotator {annotator.email}.",
        "reassigned_count": len(reassigned),
        "job_id": str(job_id),
        "new_annotator_id": str(annotator_id),
        "new_annotator_email": annotator.email,
        "segments": reassigned
    }


@router.get(
    "/job-assignments",
    summary="Get job assignment status (Admin)",
    description="List all jobs ready for annotation with their assignment status (assigned annotator or unassigned)."
)
async def get_job_assignments(
    status: Optional[str] = Query(None, description="Filter by job status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Get all jobs with their assignment status.
    
    Returns a list of jobs showing whether they are assigned to an annotator
    or still need to be assigned.
    """
    from sqlalchemy import func, select, distinct
    from app.db.models.auth import User
    from app.db.models.pipeline import PipelineJob, JobStatus
    
    # Base query: jobs that are ready for annotation
    base_query = select(PipelineJob).where(
        PipelineJob.status == JobStatus.READY_FOR_ANNOTATION
    )
    
    if status:
        base_query = base_query.where(PipelineJob.status == status)
    
    # Count total
    count_query = select(func.count(PipelineJob.id)).where(
        PipelineJob.status == JobStatus.READY_FOR_ANNOTATION
    )
    if status:
        count_query = count_query.where(PipelineJob.status == status)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated jobs
    jobs_result = await db.execute(
        base_query
        .order_by(PipelineJob.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    jobs = jobs_result.scalars().all()
    
    # Build assignment info for each job
    items = []
    for job in jobs:
        # Find segments of this job and their queue assignments
        segment_query = (
            select(
                PipelineSegment.id,
                AnnotationQueue.annotator_id,
                User.email
            )
            .outerjoin(
                AnnotationQueue,
                AnnotationQueue.segment_id == PipelineSegment.id
            )
            .outerjoin(
                User,
                AnnotationQueue.annotator_id == User.id
            )
            .where(PipelineSegment.job_id == job.id)
        )
        
        seg_result = await db.execute(segment_query)
        segments = seg_result.all()
        
        total_segments = len(segments)
        assigned_segments = sum(1 for s in segments if s.annotator_id is not None)
        
        # Determine assignment status
        if assigned_segments == 0:
            assignment_status = "unassigned"
            assigned_to = None
            assigned_to_email = None
        elif assigned_segments < total_segments:
            assignment_status = "partial"
            # Use the most common annotator
            annotator_counts = {}
            for s in segments:
                if s.annotator_id:
                    annotator_counts[s.email] = annotator_counts.get(s.email, 0) + 1
            assigned_to_email = max(annotator_counts, key=annotator_counts.get) if annotator_counts else None
            assigned_to = None
        else:
            assignment_status = "assigned"
            # All segments assigned — use the first annotator (they should all be the same)
            assigned_to_email = segments[0].email if segments else None
            assigned_to = str(segments[0].annotator_id) if segments and segments[0].annotator_id else None
        
        items.append({
            "job_id": str(job.id),
            "original_filename": job.original_filename,
            "status": job.status,
            "category": job.category,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "total_segments": total_segments,
            "assigned_segments": assigned_segments,
            "assignment_status": assignment_status,
            "assigned_to": assigned_to,
            "assigned_to_email": assigned_to_email
        })
    
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset
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
