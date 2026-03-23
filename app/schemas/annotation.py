"""
Annotation Schemas.

Pydantic models for annotation API requests and responses.
(Placeholder for future annotation endpoints)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# =============================================================================
# Annotation Edit Schemas
# =============================================================================

class AnnotationEditRequest(BaseModel):
    """Request body for creating/updating an annotation edit."""
    segment_id: str
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    old_start: Optional[float] = None
    new_start: Optional[float] = None
    old_end: Optional[float] = None
    new_end: Optional[float] = None


class AnnotationEditResponse(BaseModel):
    """Response for annotation edit operations."""
    id: str
    segment_id: str
    editor_id: str
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    old_start: Optional[float] = None
    new_start: Optional[float] = None
    old_end: Optional[float] = None
    new_end: Optional[float] = None
    created_at: str


# =============================================================================
# Review Schemas
# =============================================================================

class ReviewSubmitRequest(BaseModel):
    """Request body for submitting a review."""
    edit_id: str
    status: str  # "approved" or "rejected"
    feedback: Optional[str] = None


class ReviewResponse(BaseModel):
    """Response for review operations."""
    id: str
    edit_id: str
    curator_id: str
    status: str
    feedback: Optional[str] = None
    created_at: str


class ReviewApproveResponse(BaseModel):
    """Response for approving an annotation."""
    id: str
    edit_id: str
    status: str = "approved"
    message: str


class ReviewRejectResponse(BaseModel):
    """Response for rejecting an annotation."""
    id: str
    edit_id: str
    status: str = "rejected"
    message: str
    feedback: Optional[str] = None


# =============================================================================
# Slang Dictionary Schemas
# =============================================================================

class SlangEntryRequest(BaseModel):
    """Request body for adding/updating a slang dictionary entry."""
    slang: str
    formal: str
    context: Optional[str] = None


class SlangEntryResponse(BaseModel):
    """Response for slang dictionary operations."""
    id: str
    slang: str
    formal: str
    context: Optional[str] = None
    created_by: str
    created_at: str
    updated_at: str


class SlangDictionaryListResponse(BaseModel):
    """Response for listing slang dictionary entries."""
    entries: list[SlangEntryResponse]
    total: int
