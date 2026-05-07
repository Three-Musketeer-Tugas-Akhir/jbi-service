"""Voice Annotation Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Job List ────────────────────────────────────────────────────────

class VoiceAnnotationJobItem(BaseModel):
    """Summary of a job in the voice annotation queue."""
    job_id: str
    original_filename: str
    status: str
    total_utterances: int
    clean_count: int
    flagged_count: int
    created_at: Optional[str] = None


class VoiceAnnotationJobListResponse(BaseModel):
    """Paginated list of jobs needing voice annotation."""
    items: List[VoiceAnnotationJobItem]
    total: int
    page: int
    page_size: int
    pages: int


# ── Job Summary ─────────────────────────────────────────────────────

class VoiceAnnotationJobSummary(BaseModel):
    """Detailed summary for a single job's voice annotation status."""
    job_id: str
    original_filename: str
    status: str
    total_utterances: int
    clean_count: int
    flagged_count: int
    is_gate_passed: bool


# ── Utterance List ──────────────────────────────────────────────────

class VoiceAnnotationUtterance(BaseModel):
    """Single utterance with voice annotation data."""
    id: str
    transcript_id: str
    global_index: int
    asr_text: str
    ground_truth_text: str
    flagged_words: List[str] = Field(default_factory=list)
    has_flag: bool
    voice_annotation_status: str
    start: float
    end: float
    audio_url: Optional[str] = None
    annotator_id: Optional[str] = None
    edited_at: Optional[str] = None


class VoiceAnnotationUtteranceListResponse(BaseModel):
    """List of utterances for a job."""
    utterances: List[VoiceAnnotationUtterance]
    total: int


# ── PATCH Ground Truth ──────────────────────────────────────────────

class UpdateGroundTruthRequest(BaseModel):
    """Request body for updating ground truth text."""
    ground_truth_text: str = Field(
        ..., min_length=0,
        description="New ground-truth text. Empty string is allowed."
    )
    is_unflagged: bool = Field(
        default=False,
        description="If true, bypasses validation and forces the utterance to be CLEAN."
    )


class UpdateGroundTruthResponse(BaseModel):
    """Response after updating ground truth."""
    id: str
    ground_truth_text: str
    flagged_words: List[str]
    has_flag: bool
    voice_annotation_status: str
    old_text: str
    job_status: str
    job_clean_count: int
    job_flagged_count: int
