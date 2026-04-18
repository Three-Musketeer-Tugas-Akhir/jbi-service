"""Curation domain Pydantic schemas."""
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field


class CurationSegmentItem(BaseModel):
    """Single text segment to be normalized."""

    id: str = Field(..., description="Segment identifier")
    original_text: str = Field(..., description="Raw text before normalization")


class CurationNormalizedItem(BaseModel):
    """Single text segment after normalization."""

    id: str = Field(..., description="Segment identifier")
    original_text: str = Field(..., description="Original raw text")
    normalized_text: str = Field(..., description="Cleaned and normalized text")


class CurationNormalizeRequest(BaseModel):
    """Request body for /curation/normalize endpoint."""

    items: List[CurationSegmentItem] = Field(
        ..., description="List of text segments to normalize"
    )


class CurationNormalizeResponse(BaseModel):
    """Response body for /curation/normalize endpoint."""

    items: List[CurationNormalizedItem] = Field(
        ..., description="List of normalized text segments"
    )


class CurationApproveRequest(BaseModel):
    """Request body for /curation/approve endpoint."""

    video_id: UUID = Field(..., description="Pipeline job ID to approve for export")


class CurationStatusUpdateRequest(BaseModel):
    """Request body for updating curation status to NORMALIZED."""

    video_id: UUID = Field(..., description="Pipeline job ID to mark as normalized")
