"""Pydantic schemas for the auto-normalization endpoints."""
from typing import List, Optional

from pydantic import BaseModel, Field


class NormalizedUtterance(BaseModel):
    """Single utterance with before/after normalization results."""

    utterance_index: int = Field(..., description="Utterance index within the segment")
    segment_id: str = Field(..., description="Parent segment ID")

    # Ground truth transcript
    original_transcript: str = Field(..., description="Ground truth text before normalization")
    normalized_transcript: str = Field(..., description="Ground truth text after normalization")

    # Glosa (annotator label)
    original_glosa: str = Field(..., description="Glosa text before normalization")
    normalized_glosa: str = Field(..., description="Glosa text after SIBI normalization")

    # Timing (unchanged, included for context)
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")


class AutoNormalizeResponse(BaseModel):
    """Response for the auto-normalize preview endpoint."""

    job_id: str = Field(..., description="Pipeline job ID")
    total_ok_utterances: int = Field(..., description="Number of OK-status utterances processed")
    items: List[NormalizedUtterance] = Field(..., description="Normalized utterance results")


class NormalizedUtteranceOverride(BaseModel):
    """Manual override for a single utterance's normalized text."""

    utterance_index: int
    segment_id: str
    normalized_transcript: Optional[str] = None
    normalized_glosa: Optional[str] = None


class ApplyNormalizationRequest(BaseModel):
    """Request body for applying normalization results.

    Users can optionally override specific utterances' normalized text
    before persisting. If `overrides` is empty/null, the auto-normalized
    values are used as-is.
    """

    overrides: Optional[List[NormalizedUtteranceOverride]] = Field(
        None,
        description="Optional manual overrides for specific utterances",
    )


class ApplyNormalizationResponse(BaseModel):
    """Response after applying normalization."""

    job_id: str
    utterances_updated: int
    curation_status: str
