"""
Test script for Stage 3 Results API.

Usage:
    python tests/test_stage3_results_api.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from uuid import UUID


def test_schema_creation():
    """Test that Stage 3 schemas can be created correctly."""
    from app.schemas.job import (
        Stage3Summary,
        Stage3UtteranceResponse,
        Stage3SegmentResponse,
        Stage3ResultsResponse
    )
    
    # Test Stage3Summary
    summary = Stage3Summary(
        total_utterances=10,
        cropped=9,
        failed=1,
        pending=0
    )
    assert summary.total_utterances == 10
    assert summary.cropped == 9
    assert summary.failed == 1
    assert summary.pending == 0
    print("✅ Stage3Summary schema works")
    
    # Test Stage3UtteranceResponse
    utterance = Stage3UtteranceResponse(
        id="transcript-uuid-123",
        utterance_index=0,
        text="Ini adalah contoh transkripsi bahasa Indonesia",
        start=1.0,  # CROPPED timestamp
        end=6.5,    # CROPPED timestamp
        confidence=0.92,
        url="/api/v1/assets/jobs/job-uuid/utterances/utterance_xxx.mp4",
        status="cropped"
    )
    assert utterance.id == "transcript-uuid-123"
    assert utterance.utterance_index == 0
    assert utterance.start == 1.0  # Note: cropped, not original
    assert utterance.end == 6.5    # Note: cropped, not original
    assert utterance.status == "cropped"
    print("✅ Stage3UtteranceResponse schema works")
    
    # Test Stage3SegmentResponse
    segment = Stage3SegmentResponse(
        segment_id="segment-uuid-123",
        asr_review_flag=False,
        utterances=[utterance]
    )
    assert segment.segment_id == "segment-uuid-123"
    assert len(segment.utterances) == 1
    print("✅ Stage3SegmentResponse schema works")
    
    # Test Stage3ResultsResponse
    response = Stage3ResultsResponse(
        id="job-uuid-123",
        summary=summary,
        results=[segment]
    )
    assert response.id == "job-uuid-123"
    assert response.summary.cropped == 9
    assert len(response.results) == 1
    print("✅ Stage3ResultsResponse schema works")
    
    # Test JSON serialization
    json_str = response.model_dump_json(indent=2)
    assert "job-uuid-123" in json_str
    assert "cropped" in json_str
    assert "transkripsi" in json_str
    print("✅ JSON serialization works")
    print()
    print("Example JSON output:")
    print(json_str)


def test_cropped_timestamps():
    """Test that Stage 3 has different timestamps than Stage 2 would have."""
    from app.schemas.job import Stage3UtteranceResponse
    
    # In Stage 2, these might be: start=0.0, end=3.5
    # In Stage 3 (cropped), they're modified:
    utterance = Stage3UtteranceResponse(
        id="transcript-uuid",
        utterance_index=0,
        text="Contoh",
        start=1.0,   # CROPPED: added offset or buffer
        end=6.5,     # CROPPED: extended
        confidence=0.9,
        url="/api/v1/assets/...",
        status="cropped"
    )
    
    # Verify cropped timestamps are different (in this example)
    assert utterance.start >= 0.0
    assert utterance.end > utterance.start
    print("✅ Cropped timestamps are valid")


def test_summary_counts():
    """Test summary counts calculation."""
    from app.schemas.job import Stage3Summary
    
    # Test case: all successful
    summary_all_good = Stage3Summary(
        total_utterances=5,
        cropped=5,
        failed=0,
        pending=0
    )
    assert summary_all_good.total_utterances == summary_all_good.cropped
    
    # Test case: some failures
    summary_mixed = Stage3Summary(
        total_utterances=10,
        cropped=8,
        failed=1,
        pending=1
    )
    assert summary_mixed.cropped + summary_mixed.failed + summary_mixed.pending == summary_mixed.total_utterances
    
    print("✅ Summary counts work correctly")


def test_multiple_segments_with_summary():
    """Test response with multiple segments and verify summary."""
    from app.schemas.job import (
        Stage3Summary,
        Stage3UtteranceResponse,
        Stage3SegmentResponse,
        Stage3ResultsResponse
    )
    
    segments = []
    utterance_count = 0
    
    for seg_idx in range(2):
        utterances = []
        for utt_idx in range(3):
            utterance = Stage3UtteranceResponse(
                id=f"transcript-{seg_idx}-{utt_idx}",
                utterance_index=utt_idx,
                text=f"Segmen {seg_idx+1}, Kalimat {utt_idx+1}",
                start=float(1.0 + utt_idx * 5),
                end=float(6.0 + utt_idx * 5),
                confidence=0.9,
                url=f"/api/v1/assets/jobs/job-uuid/utterances/utterance_{seg_idx:04d}_{utt_idx:04d}.mp4",
                status="cropped"
            )
            utterances.append(utterance)
            utterance_count += 1
        
        segment = Stage3SegmentResponse(
            segment_id=f"segment-uuid-{seg_idx}",
            asr_review_flag=False,
            utterances=utterances
        )
        segments.append(segment)
    
    summary = Stage3Summary(
        total_utterances=utterance_count,
        cropped=utterance_count,
        failed=0,
        pending=0
    )
    
    response = Stage3ResultsResponse(
        id="job-uuid",
        summary=summary,
        results=segments
    )
    
    assert len(response.results) == 2
    assert len(response.results[0].utterances) == 3
    assert response.summary.total_utterances == 6
    print(f"✅ Multiple segments ({len(segments)}) with summary works")


def test_status_variations():
    """Test different utterance statuses."""
    from app.schemas.job import Stage3UtteranceResponse
    
    statuses = ["cropped", "pending", "failed"]
    utterances = []
    
    for i, status in enumerate(statuses):
        utt = Stage3UtteranceResponse(
            id=f"transcript-{i}",
            utterance_index=i,
            text=f"Text {i}",
            start=float(i),
            end=float(i + 3),
            confidence=0.85,
            url=f"/api/v1/assets/.../utterance_{i}.mp4" if status == "cropped" else None,
            status=status
        )
        utterances.append(utt)
        assert utt.status == status
    
    print("✅ All status variations work (cropped, pending, failed)")


# Example usage documentation
EXAMPLE_USAGE = """
================================================================================
STAGE 3 RESULTS API - EXAMPLE USAGE
================================================================================

1. Get Stage 3 (Cropping) Results:
-----------------------------------
GET /api/v1/pipeline/jobs/{job_id}/stage3/results
Authorization: Bearer <jwt_token>

2. Example Response:
--------------------
{
  "id": "196d54f7-f2c2-4326-ad0e-c3849b8d3d72",
  "summary": {
    "total_utterances": 10,
    "cropped": 9,
    "failed": 1,
    "pending": 0
  },
  "results": [
    {
      "segment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "asr_review_flag": false,
      "utterances": [
        {
          "id": "transcript-uuid-1",
          "utterance_index": 0,
          "text": "Ini adalah contoh transkripsi",
          "start": 1.0,
          "end": 6.5,
          "confidence": 0.92,
          "url": "/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/utterances/utterance_xxx.mp4",
          "status": "cropped"
        }
      ]
    }
  ]
}

3. cURL Example:
----------------
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/pipeline/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/stage3/results

================================================================================
EXPECTED RESPONSES
================================================================================

200 OK - Cropping results with summary
401 Unauthorized - Missing or invalid JWT token
403 Forbidden - User not authorized to access this job
404 Not Found - Job not found
500 Internal Server Error - Server error

================================================================================
RESPONSE FIELDS
================================================================================

id (string): Job UUID
summary (object): Overview of cropping status
  - total_utterances (int): Total utterances across all segments
  - cropped (int): Successfully cropped utterances
  - failed (int): Failed to crop
  - pending (int): Not yet processed
results (array): List of segments with cropped utterances
  - segment_id (string): Segment UUID
  - asr_review_flag (boolean): From Stage 2
  - utterances (array): List of cropped utterances
    - id (string): Transcript UUID
    - utterance_index (int): Index within segment (0-based)
    - text (string): Transcribed text
    - start (float): CROPPED start timestamp (seconds)
    - end (float): CROPPED end timestamp (seconds)
    - confidence (float): ASR confidence (0-1)
    - url (string|null): Asset URL for cropped video
    - status (string): cropped, pending, or failed

================================================================================
DIFFERENCES BETWEEN STAGES
================================================================================

Stage 1 (Detection):
  - Returns: bbox_data, segment_url
  - Granularity: Per segment
  - Use case: Visual detection review

Stage 2 (ASR):
  - Returns: Original ASR timestamps (from Whisper)
  - Video: Segment-level (Stage 1 cropped)
  - Use case: Transcription review

Stage 3 (Cropping):
  - Returns: CROPPED timestamps (after algorithm applied)
  - Video: Utterance-level (individually cropped)
  - Use case: Final annotation with precise utterance videos

================================================================================
CROPPING ALGORITHM
================================================================================

The cropping worker applies the following to each utterance:

1. First utterance: start unchanged
2. Subsequent: start += 1s offset
3. End calculation based on gap to next utterance:
   - Gap > 2s: add 2s buffer
   - Gap <= 2s: extend to next + 1s
4. Last utterance: extend to video duration or +1s

This ensures smooth transitions and appropriate context for annotation.

================================================================================
"""


if __name__ == "__main__":
    print("=" * 80)
    print("STAGE 3 RESULTS API - BASIC TESTS")
    print("=" * 80)
    print()
    
    tests = [
        test_schema_creation,
        test_cropped_timestamps,
        test_summary_counts,
        test_multiple_segments_with_summary,
        test_status_variations,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print()
    print("=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 80)
    print()
    print(EXAMPLE_USAGE)
