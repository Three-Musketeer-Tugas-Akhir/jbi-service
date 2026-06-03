"""faster-whisper-based ASR transcription service."""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, NamedTuple, Optional
from dataclasses import dataclass

from faster_whisper import WhisperModel

from app.core.config import settings
from app.core.exceptions import ProcessingError

logger = logging.getLogger(__name__)


class TranscriptionSegment(NamedTuple):
    """Single transcription segment result."""
    start: float  # seconds
    end: float    # seconds
    text: str
    confidence: float


@dataclass
class TranscriptionResult:
    """Complete transcription result for a video segment."""
    segments: List[TranscriptionSegment]
    text: str  # Full concatenated text
    average_confidence: float
    
    @property
    def start(self) -> float:
        """Start time of first segment."""
        return self.segments[0].start if self.segments else 0.0
    
    @property
    def end(self) -> float:
        """End time of last segment."""
        return self.segments[-1].end if self.segments else 0.0


class TranscriberService:
    """
    faster-whisper-based ASR transcription service.
    
    Follows implementation from asr_code.ipynb exactly.
    Loads model once and reuses (singleton pattern).
    Supports configurable model sizes and compute types.
    """
    
    _instance = None
    _lock = threading.Lock()
    _model = None
    _model_size = None
    _compute_type = None
    _executor = ThreadPoolExecutor(max_workers=1)
    
    # Default configuration
    DEFAULT_MODEL_SIZE = "base"
    DEFAULT_COMPUTE_TYPE = "int8"
    DEFAULT_BEAM_SIZE = 5
    DEFAULT_BEST_OF = 5
    DEFAULT_PATIENCE = 1.0
    DEFAULT_LANGUAGE = "id"
    
    def __new__(cls):
        """Singleton pattern for model reuse - thread safe."""
        if cls._instance is None:
            with cls._lock:
                # Double-check after acquiring lock
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize transcriber (model loaded lazily)."""
        if self._model_size is None:
            self._model_size = settings.whisper_model_size or self.DEFAULT_MODEL_SIZE
            self._compute_type = settings.whisper_compute_type or self.DEFAULT_COMPUTE_TYPE
    
    def _load_model(self) -> WhisperModel:
        """Load faster-whisper model (cached)."""
        if self._model is None:
            logger.info(
                f"Loading faster-whisper model: {self._model_size} "
                f"(compute_type={self._compute_type})"
            )
            try:
                # Determine device based on compute type
                # GPU requires float16 or int8_float16; pure int8 uses CPU
                device = "cuda" if self._compute_type in ("float16", "int8_float16") else "cpu"
                if settings.force_cpu:
                    device = "cpu"
                
                self._model = WhisperModel(
                    self._model_size,
                    device=device,
                    compute_type=self._compute_type,
                    download_root=settings.model_cache_dir or "model_weights"
                )
                logger.info("faster-whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load faster-whisper model: {e}")
                raise ProcessingError(f"ASR model loading failed: {e}")
        return self._model
    
    async def transcribe(
        self,
        audio_path: Path,
        language: str = None,
        beam_size: int = None,
        patience: float = None,
        condition_on_previous_text: bool = None
    ) -> TranscriptionResult:
        """
        Transcribe audio file using faster-whisper.
        
        Args:
            audio_path: Path to audio file (WAV/MP3)
            language: Audio language code (default: "id" for Indonesian)
            beam_size: Beam search size (default: 5)
            patience: Beam search patience (default: 1.0)
            condition_on_previous_text: Use previous text as context (default: True)
            
        Returns:
            TranscriptionResult with segments and metadata
            
        Raises:
            ProcessingError: If transcription fails
        """
        language = language or self.DEFAULT_LANGUAGE
        beam_size = beam_size or self.DEFAULT_BEAM_SIZE
        patience = patience or self.DEFAULT_PATIENCE
        
        if condition_on_previous_text is None:
            condition_on_previous_text = True
        
        model = self._load_model()
        
        try:
            # Run blocking transcription in thread executor to avoid blocking event loop
            # This allows other async tasks (like Kafka heartbeat) to run during inference
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._transcribe_sync,
                model,
                audio_path,
                language,
                beam_size,
                patience,
                condition_on_previous_text
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise ProcessingError(f"ASR transcription failed: {e}")
    
    def _transcribe_sync(
        self,
        model,
        audio_path: Path,
        language: str,
        beam_size: int,
        patience: float,
        condition_on_previous_text: bool
    ) -> TranscriptionResult:
        """
        Synchronous transcription method to run in thread executor.
        
        This method contains the blocking faster-whisper inference logic
        that must not block the asyncio event loop.
        """
        # Run transcription
        segments_gen, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=beam_size,
            patience=patience,
            condition_on_previous_text=condition_on_previous_text,
            word_timestamps=False  # Segment-level timestamps
        )
        
        # Collect segments
        segments = []
        total_confidence = 0.0
        segment_count = 0
        full_text_parts = []
        
        for segment in segments_gen:
            # Calculate average confidence for segment
            # faster-whisper provides avg_logprob which we convert to confidence
            # Higher avg_logprob = higher confidence (less negative is better)
            # Typical range: -1.0 (high confidence) to -3.0 (low confidence)
            if hasattr(segment, 'avg_logprob') and segment.avg_logprob is not None:
                # Convert logprob to approximate confidence (0-1 scale)
                # Clamp between 0 and 1
                confidence = min(1.0, max(0.0, 1.0 + segment.avg_logprob))
            else:
                # Fallback: use heuristic based on no_speech_prob
                confidence = 1.0 - (info.no_speech_prob if hasattr(info, 'no_speech_prob') else 0.0)
            
            transcription_segment = TranscriptionSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text.strip(),
                confidence=confidence
            )
            segments.append(transcription_segment)
            full_text_parts.append(segment.text.strip())
            total_confidence += confidence
            segment_count += 1
        
        # Calculate average confidence
        average_confidence = total_confidence / segment_count if segment_count > 0 else 0.0
        
        result = TranscriptionResult(
            segments=segments,
            text=" ".join(full_text_parts),
            average_confidence=average_confidence
        )
        
        logger.info(
            f"Transcription complete: {segment_count} segments, "
            f"avg_confidence={average_confidence:.2f}"
        )
        return result
    
    def format_segments_txt(
        self,
        result: TranscriptionResult,
        segment_offset: float = 0.0
    ) -> str:
        """
        Format transcription result as segments.txt.
        
        Format: [HH:MM:SS.sss -> HH:MM:SS.sss] transcript text
        
        Args:
            result: TranscriptionResult
            segment_offset: Time offset to add to all timestamps (for job-level timing)
            
        Returns:
            segments.txt formatted string
        """
        lines = []
        for seg in result.segments:
            start = seg.start + segment_offset
            end = seg.end + segment_offset
            start_str = self._format_timestamp(start)
            end_str = self._format_timestamp(end)
            lines.append(f"[{start_str} -> {end_str}] {seg.text}")
        return "\n".join(lines)
    
    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS.sss."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


# Global singleton
_transcriber_service_instance = None


def get_transcriber_service() -> TranscriberService:
    """Get transcriber service singleton."""
    global _transcriber_service_instance
    if _transcriber_service_instance is None:
        _transcriber_service_instance = TranscriberService()
    return _transcriber_service_instance
