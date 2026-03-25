"""Segment schemas with confidence score."""
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class SegmentWithConfidence(BaseModel):
    """Segment with ASR confidence information."""
    segment_id: UUID
    asr_text: Optional[str]
    asr_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    # Confidence indicators
    confidence_level: str  # "high", "medium", "low"
    requires_attention: bool
    
    @classmethod
    def from_db_segment(cls, segment):
        """Create from database segment."""
        confidence = segment.asr_confidence
        
        if confidence is None:
            level = "unknown"
            requires_attention = False
        elif confidence >= 0.9:
            level = "high"
            requires_attention = False
        elif confidence >= 0.5:
            level = "medium"
            requires_attention = False
        else:
            level = "low"
            requires_attention = True
        
        return cls(
            segment_id=segment.id,
            asr_text=segment.asr_text,
            asr_confidence=confidence,
            confidence_level=level,
            requires_attention=requires_attention
        )
