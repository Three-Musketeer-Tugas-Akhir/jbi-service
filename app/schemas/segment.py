"""Segment schemas with confidence score."""
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


class TranscriptUtterance(BaseModel):
    """Individual utterance from ASR."""
    utterance_index: int
    text: str
    start: float
    end: float
    confidence: float
    video_path: Optional[str] = None


class SegmentWithConfidence(BaseModel):
    """Segment with ASR confidence information (from utterances)."""
    segment_id: UUID
    utterances: List[TranscriptUtterance]
    avg_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    # Confidence indicators
    confidence_level: str  # "high", "medium", "low"
    requires_attention: bool
    
    @classmethod
    def from_db_segment(cls, segment):
        """Create from database segment with utterances."""
        # Get utterances from relationship
        utterances = [
            TranscriptUtterance(
                utterance_index=u.utterance_index,
                text=u.text,
                start=u.start,
                end=u.end,
                confidence=u.confidence,
                video_path=u.video_path
            )
            for u in (segment.transcripts or [])
        ]
        
        # Calculate average confidence from utterances
        if utterances:
            avg_confidence = sum(u.confidence for u in utterances) / len(utterances)
        else:
            avg_confidence = None
        
        # Determine confidence level
        if avg_confidence is None:
            level = "unknown"
            requires_attention = False
        elif avg_confidence >= 0.9:
            level = "high"
            requires_attention = False
        elif avg_confidence >= 0.5:
            level = "medium"
            requires_attention = False
        else:
            level = "low"
            requires_attention = True
        
        return cls(
            segment_id=segment.id,
            utterances=utterances,
            avg_confidence=avg_confidence,
            confidence_level=level,
            requires_attention=requires_attention
        )
