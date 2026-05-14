"""
My Dashboard Service.

Returns personalized dashboard data based on user role:
- annotator: jobs assigned to them via annotation_queue
- curator: jobs ready for or undergoing curation
"""
from __future__ import annotations

import logging
from uuid import UUID
from typing import Any, Dict, List

from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import AnnotationQueue
from app.db.models.pipeline import PipelineJob, PipelineSegment
from app.db.models.auth import User

logger = logging.getLogger(__name__)


# ── Status display helpers ────────────────────────────────────────────────────

JOB_STATUS_LABEL: Dict[str, str] = {
    "UPLOADED": "Diunggah",
    "PROCESSING": "Diproses",
    "READY_FOR_ANNOTATION": "Siap Anotasi",
    "NEEDS_VOICE_ANNOTATION": "Perlu Anotasi Suara",
    "VOICE_ANNOTATION_IN_PROGRESS": "Anotasi Suara Berlangsung",
    "ANNOTATION_IN_PROGRESS": "Anotasi Berlangsung",
    "ANNOTATION_COMPLETED": "Anotasi Selesai",
    "READY_FOR_EXPORT": "Siap Ekspor",
    "COMPLETED": "Selesai",
    "FAILED": "Gagal",
    "CANCELLED": "Dibatalkan",
}

QUEUE_STATUS_LABEL: Dict[str, str] = {
    "ASSIGNED": "Ditugaskan",
    "IN_PROGRESS": "Sedang Dikerjakan",
    "COMPLETED": "Selesai",
}

CURATION_STATUS_LABEL: Dict[str, str] = {
    "ANNOTATED": "Menunggu Kurasi",
    "READY_TO_BE_NORMALIZED": "Siap Normalisasi",
    "NORMALIZING": "Sedang Dinormalisasi",
    "NORMALIZED": "Selesai Dinormalisasi",
    "READY_TO_EXPORT": "Siap Ekspor",
}


# ── Annotator Dashboard ───────────────────────────────────────────────────────

async def get_annotator_dashboard(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """
    Returns dashboard data for an annotator.
    Queries annotation_queue for segments assigned to this user,
    groups by job, and computes progress stats.
    """
    # Fetch all queue entries for this annotator, joined to segment + job
    result = await db.execute(
        select(
            PipelineJob.id.label("job_id"),
            PipelineJob.original_filename,
            PipelineJob.status.label("job_status"),
            PipelineJob.created_at.label("job_created_at"),
            AnnotationQueue.status.label("queue_status"),
            AnnotationQueue.assigned_at,
            AnnotationQueue.due_date,
            AnnotationQueue.completed_at,
            PipelineSegment.id.label("segment_id"),
            PipelineSegment.segment_index,
        )
        .join(PipelineSegment, AnnotationQueue.segment_id == PipelineSegment.id)
        .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
        .where(AnnotationQueue.annotator_id == user_id)
        .order_by(PipelineJob.id, PipelineSegment.segment_index)
    )
    rows = result.mappings().all()

    # Group by job
    jobs_map: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        jid = str(row["job_id"])
        if jid not in jobs_map:
            jobs_map[jid] = {
                "job_id": jid,
                "original_filename": row["original_filename"],
                "job_status": row["job_status"],
                "job_status_label": JOB_STATUS_LABEL.get(row["job_status"], row["job_status"]),
                "assigned_at": row["assigned_at"].isoformat() if row["assigned_at"] else None,
                "due_date": row["due_date"].isoformat() if row["due_date"] else None,
                "total_segments": 0,
                "completed_segments": 0,
                "in_progress_segments": 0,
                "pending_segments": 0,
            }
        jobs_map[jid]["total_segments"] += 1
        qs = row["queue_status"]
        if qs == "COMPLETED":
            jobs_map[jid]["completed_segments"] += 1
        elif qs == "IN_PROGRESS":
            jobs_map[jid]["in_progress_segments"] += 1
        else:
            jobs_map[jid]["pending_segments"] += 1

    # Enrich each job with progress percentage and queue_status summary
    job_list = []
    total_segments = 0
    total_completed = 0
    total_in_progress = 0
    total_pending = 0

    for job in jobs_map.values():
        t = job["total_segments"]
        c = job["completed_segments"]
        ip = job["in_progress_segments"]
        p = job["pending_segments"]

        job["progress_percent"] = round((c / t * 100) if t > 0 else 0, 1)

        # Overall queue status for this job
        if c == t:
            job["queue_status"] = "COMPLETED"
            job["queue_status_label"] = "Selesai"
        elif ip > 0 or c > 0:
            job["queue_status"] = "IN_PROGRESS"
            job["queue_status_label"] = "Sedang Dikerjakan"
        else:
            job["queue_status"] = "ASSIGNED"
            job["queue_status_label"] = "Ditugaskan"

        job_list.append(job)
        total_segments += t
        total_completed += c
        total_in_progress += ip
        total_pending += p

    # Sort: in-progress first, then assigned, then completed
    def sort_key(j):
        order = {"IN_PROGRESS": 0, "ASSIGNED": 1, "COMPLETED": 2}
        return order.get(j["queue_status"], 99)

    job_list.sort(key=sort_key)

    overall_progress = round((total_completed / total_segments * 100) if total_segments > 0 else 0, 1)

    return {
        "role": "annotator",
        "stats": {
            "total_segments": total_segments,
            "completed_segments": total_completed,
            "in_progress_segments": total_in_progress,
            "pending_segments": total_pending,
            "overall_progress_percent": overall_progress,
            "total_jobs": len(job_list),
        },
        "jobs": job_list,
    }


# ── Curator Dashboard ─────────────────────────────────────────────────────────

async def get_curator_dashboard(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """
    Returns dashboard data for a curator.
    Shows all jobs that are in curation-relevant statuses.
    Curators are not assigned to specific jobs — they see the full queue.
    """
    CURATION_STATUSES = [
        "ANNOTATED",
        "READY_TO_BE_NORMALIZED",
        "NORMALIZING",
        "NORMALIZED",
        "READY_TO_EXPORT",
    ]

    result = await db.execute(
        select(
            PipelineJob.id.label("job_id"),
            PipelineJob.original_filename,
            PipelineJob.status.label("job_status"),
            PipelineJob.curation_status,
            PipelineJob.created_at,
            PipelineJob.updated_at,
            func.count(PipelineSegment.id).label("total_segments"),
        )
        .outerjoin(PipelineSegment, PipelineJob.id == PipelineSegment.job_id)
        .where(PipelineJob.curation_status.in_(CURATION_STATUSES))
        .group_by(PipelineJob.id)
        .order_by(
            # ANNOTATED (needs action) first, then NORMALIZING, then rest
            case(
                (PipelineJob.curation_status == "ANNOTATED", 0),
                (PipelineJob.curation_status == "READY_TO_BE_NORMALIZED", 1),
                (PipelineJob.curation_status == "NORMALIZING", 2),
                (PipelineJob.curation_status == "NORMALIZED", 3),
                else_=4,
            ),
            PipelineJob.updated_at.desc(),
        )
    )
    rows = result.mappings().all()

    job_list = []
    pending_review = 0
    in_normalization = 0
    completed_normalization = 0

    for row in rows:
        cs = row["curation_status"] or ""
        job = {
            "job_id": str(row["job_id"]),
            "original_filename": row["original_filename"],
            "job_status": row["job_status"],
            "curation_status": cs,
            "curation_status_label": CURATION_STATUS_LABEL.get(cs, cs),
            "total_segments": row["total_segments"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        job_list.append(job)

        if cs in ("ANNOTATED", "READY_TO_BE_NORMALIZED"):
            pending_review += 1
        elif cs == "NORMALIZING":
            in_normalization += 1
        elif cs in ("NORMALIZED", "READY_TO_EXPORT"):
            completed_normalization += 1

    return {
        "role": "curator",
        "stats": {
            "total_jobs": len(job_list),
            "pending_review": pending_review,
            "in_normalization": in_normalization,
            "completed_normalization": completed_normalization,
        },
        "jobs": job_list,
    }
