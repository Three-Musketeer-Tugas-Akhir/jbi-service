"""Dashboard aggregation service."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

from sqlalchemy import select, func, and_, text, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineJob, PipelineSegment, PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.db.models.audit import AuditLog


logger = logging.getLogger(__name__)


class DashboardService:
    """Service for aggregating dashboard metrics."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all dashboard data in a single aggregated response."""
        stats = await self._get_stats()
        pipeline_progress = await self._get_pipeline_progress()
        conversion_rates = self._calculate_conversion_rates(pipeline_progress)
        system_activities = await self._get_system_activities()

        return {
            "stats": stats,
            "pipeline_progress": pipeline_progress,
            "conversion_rates": conversion_rates,
            "system_activities": system_activities,
        }

    async def _get_stats(self) -> List[Dict[str, Any]]:
        """Get top-level statistics cards."""
        try:
            # Total SIBI videos
            total_videos_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(PipelineJob.category == "SIBI")
            )
            total_videos = total_videos_result.scalar() or 0

            # SIBI videos in last 12 weeks
            twelve_weeks_ago = datetime.utcnow() - timedelta(weeks=12)
            recent_videos_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        PipelineJob.created_at >= twelve_weeks_ago,
                    )
                )
            )
            recent_videos = recent_videos_result.scalar() or 0

            # Total segments (chunks) for SIBI
            total_chunks_result = await self.db.execute(
                select(func.count(PipelineSegment.id))
                .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
                .where(PipelineJob.category == "SIBI")
            )
            total_chunks = total_chunks_result.scalar() or 0

            # Segments created today (proxy via job created_at since segments have no created_at)
            today = datetime.utcnow().date()
            chunks_today_result = await self.db.execute(
                select(func.count(PipelineSegment.id))
                .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
                .where(
                    and_(
                        PipelineJob.category == "SIBI",
                        func.date(PipelineJob.created_at) == today,
                    )
                )
            )
            chunks_today = chunks_today_result.scalar() or 0

            # Total annotation edits for SIBI
            total_annotations_result = await self.db.execute(
                select(func.count(AnnotationEdit.id))
                .join(PipelineSegment, AnnotationEdit.segment_id == PipelineSegment.id)
                .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
                .where(
                    and_(
                        PipelineJob.category == "SIBI",
                        AnnotationEdit.is_deleted == False,
                    )
                )
            )
            total_annotations = total_annotations_result.scalar() or 0

            # Total segments with transcripts for SIBI (denominator for annotation %)
            total_transcript_segments_result = await self.db.execute(
                select(func.count(PipelineSegment.id))
                .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
                .where(
                    and_(
                        PipelineJob.category == "SIBI",
                        exists(
                            select(1).where(
                                PipelineTranscript.segment_id == PipelineSegment.id
                            )
                        ),
                    )
                )
            )
            total_transcript_segments = total_transcript_segments_result.scalar() or 0

            annotation_pct = 0.0
            if total_transcript_segments > 0:
                annotation_pct = round(
                    (total_annotations / total_transcript_segments) * 100, 1
                )

            # Export ready: jobs with curation_status READY_TO_EXPORT or NORMALIZED
            export_ready_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        PipelineJob.curation_status.in_(
                            ["READY_TO_EXPORT", "NORMALIZED"]
                        ),
                    )
                )
            )
            export_ready = export_ready_result.scalar() or 0

            export_pct = 0.0
            if total_videos > 0:
                export_pct = round((export_ready / total_videos) * 100, 1)

            return [
                {
                    "label": "TOTAL VIDEO SIBI",
                    "value": total_videos,
                    "sublabel": f"+{recent_videos} minggu ini",
                    "icon": "video",
                },
                {
                    "label": "CHUNKS TEREKSTRAK",
                    "value": total_chunks,
                    "sublabel": f"+{chunks_today} hari ini",
                    "icon": "scissors",
                },
                {
                    "label": "KALIMAT TERANOTASI",
                    "value": total_annotations,
                    "sublabel": f"{annotation_pct}% selesai",
                    "icon": "file-text",
                },
                {
                    "label": "SIAP EXPORT",
                    "value": export_ready,
                    "sublabel": f"{export_pct}% dari total",
                    "icon": "package",
                },
            ]
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            return []

    async def _get_pipeline_progress(self) -> List[Dict[str, Any]]:
        """Get pipeline progress tracker stages."""
        try:
            # Base: total SIBI videos
            total_videos_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(PipelineJob.category == "SIBI")
            )
            total_videos = total_videos_result.scalar() or 0

            # CV-1 Extract: SIBI videos with at least 1 segment
            cv_extract_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        exists(
                            select(1).where(
                                PipelineSegment.job_id == PipelineJob.id
                            )
                        ),
                    )
                )
            )
            cv_extract = cv_extract_result.scalar() or 0

            # ASR Transcribe: SIBI videos with at least 1 segment that has transcripts
            asr_transcribe_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        exists(
                            select(1).where(
                                PipelineSegment.job_id == PipelineJob.id
                            ).where(
                                exists(
                                    select(1).where(
                                        PipelineTranscript.segment_id
                                        == PipelineSegment.id
                                    )
                                )
                            )
                        ),
                    )
                )
            )
            asr_transcribe = asr_transcribe_result.scalar() or 0

            # Review & Anotasi: SIBI videos with at least 1 segment that has annotation edits
            review_annotate_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        exists(
                            select(1).where(
                                PipelineSegment.job_id == PipelineJob.id
                            ).where(
                                exists(
                                    select(1).where(
                                        AnnotationEdit.segment_id
                                        == PipelineSegment.id
                                    ).where(AnnotationEdit.is_deleted == False)
                                )
                            )
                        ),
                    )
                )
            )
            review_annotate = review_annotate_result.scalar() or 0

            # Kurasi: SIBI videos with at least 1 annotation edit that is APPROVED or has normalized_text
            kurasi_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        exists(
                            select(1).where(
                                PipelineSegment.job_id == PipelineJob.id
                            ).where(
                                exists(
                                    select(1).where(
                                        AnnotationEdit.segment_id
                                        == PipelineSegment.id
                                    ).where(AnnotationEdit.is_deleted == False).where(
                                        AnnotationEdit.status == "APPROVED"
                                    )
                                )
                            )
                        ),
                    )
                )
            )
            kurasi = kurasi_result.scalar() or 0

            # Export Ready: SIBI jobs with curation_status READY_TO_EXPORT
            export_ready_result = await self.db.execute(
                select(func.count(PipelineJob.id)).where(
                    and_(
                        PipelineJob.category == "SIBI",
                        PipelineJob.curation_status == "READY_TO_EXPORT",
                    )
                )
            )
            export_ready = export_ready_result.scalar() or 0

            stages = [
                {
                    "name": "Klasifikasi",
                    "current": total_videos,
                    "total": total_videos,
                    "percentage": 100.0 if total_videos > 0 else 0.0,
                    "color": "emerald",
                },
                {
                    "name": "CV-1 Extract",
                    "current": cv_extract,
                    "total": total_videos,
                    "percentage": round((cv_extract / total_videos) * 100, 1)
                    if total_videos > 0
                    else 0.0,
                    "color": "blue",
                },
                {
                    "name": "ASR Transcribe",
                    "current": asr_transcribe,
                    "total": cv_extract,
                    "percentage": round((asr_transcribe / cv_extract) * 100, 1)
                    if cv_extract > 0
                    else 0.0,
                    "color": "violet",
                },
                {
                    "name": "Review & Anotasi",
                    "current": review_annotate,
                    "total": asr_transcribe,
                    "percentage": round((review_annotate / asr_transcribe) * 100, 1)
                    if asr_transcribe > 0
                    else 0.0,
                    "color": "amber",
                },
                {
                    "name": "Kurasi",
                    "current": kurasi,
                    "total": review_annotate,
                    "percentage": round((kurasi / review_annotate) * 100, 1)
                    if review_annotate > 0
                    else 0.0,
                    "color": "orange",
                },
                {
                    "name": "Export Ready",
                    "current": export_ready,
                    "total": kurasi,
                    "percentage": round((export_ready / kurasi) * 100, 1)
                    if kurasi > 0
                    else 0.0,
                    "color": "emerald",
                },
            ]
            return stages
        except Exception as e:
            logger.error(f"Error getting pipeline progress: {e}")
            return []

    def _calculate_conversion_rates(
        self, pipeline_progress: List[Dict[str, Any]]
    ) -> List[float]:
        """Calculate conversion rates from pipeline progress."""
        if not pipeline_progress:
            return []

        rates = []
        for i, stage in enumerate(pipeline_progress):
            total = stage.get("total", 0)
            if total > 0:
                rates.append(round((stage["current"] / total) * 100, 0))
            else:
                rates.append(0.0)
        return rates

    async def _get_system_activities(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent system activities from audit logs."""
        try:
            from app.db.models.auth import User

            result = await self.db.execute(
                select(AuditLog, User.email)
                .outerjoin(User, AuditLog.actor_id == User.id)
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
            )

            activities = []
            for row in result.all():
                log, email = row
                actor = email or "Sistem"
                description = self._format_audit_action(log.action, actor)
                activities.append(
                    {
                        "action": log.action,
                        "description": description,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                    }
                )
            return activities
        except Exception as e:
            logger.error(f"Error getting system activities: {e}")
            return []

    def _format_audit_action(self, action: str, actor: str) -> str:
        """Format audit action into human readable description."""
        action_map = {
            "user.login": f"User Login",
            "user.logout": f"User Logout",
            "user.created": f"User dibuat oleh {actor}",
            "user.role_changed": f"Role diubah oleh {actor}",
            "user.deactivated": f"User dinonaktifkan oleh {actor}",
            "user.reactivated": f"User diaktifkan kembali oleh {actor}",
            "job.created": f"Job baru ditambahkan oleh {actor}",
            "job.cancelled": f"Job dibatalkan oleh {actor}",
            "annotation.created": f"Anotasi dibuat oleh {actor}",
            "annotation.submitted": f"Anotasi dikirim oleh {actor}",
            "annotation.approved": f"Anotasi disetujui oleh {actor}",
            "annotation.rejected": f"Anotasi ditolak oleh {actor}",
            "pipeline.stage_started": f"Pipeline stage dimulai",
            "pipeline.stage_completed": f"Pipeline stage selesai",
            "upload.completed": f"Upload video selesai oleh {actor}",
        }
        return action_map.get(action, action)


# Factory function
def get_dashboard_service(db: AsyncSession) -> DashboardService:
    return DashboardService(db)
