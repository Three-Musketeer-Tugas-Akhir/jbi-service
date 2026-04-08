"""
Test script for Stage 2 Results API.

Usage:
    python tests/test_stage2_results_api.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from uuid import UUID


def test_schema_creation():
    """Test that Stage 2 schemas can be created correctly."""
    from app.schemas.job import (
        Stage2UtteranceResponse,
        Stage2SegmentResponse,
        Stage2ResultsResponse
    )
    
    # Test Stage2UtteranceResponse
    utterance = Stage2UtteranceResponse(
        id="transcript-uuid-123",
        utterance_index=0,
        text="Ini adalah contoh transkripsi bahasa Indonesia",
        start=0.0,
        end=3.5,
        confidence=0.92,
        url="/api/v1/assets/jobs/job-uuid/utterances/utterance_0000_0000.mp4",
        status="cropped"
    )
    assert utterance.id == "transcript-uuid-123"
    assert utterance.utterance_index == 0
    assert utterance.text == "Ini adalah contoh transkripsi bahasa Indonesia"
    assert utterance.start == 0.0
    assert utterance.end == 3.5
    assert utterance.confidence == 0.92
    assert utterance.status == "cropped"
    print("✅ Stage2UtteranceResponse schema works")
    
    # Test Stage2SegmentResponse
    segment = Stage2SegmentResponse(
        segment_id="segment-uuid-123",
        asr_review_flag=False,
        utterances=[utterance]
    )
    assert segment.segment_id == "segment-uuid-123"
    assert segment.asr_review_flag == False
    assert len(segment.utterances) == 1
    print("✅ Stage2SegmentResponse schema works")
    
    # Test Stage2ResultsResponse
    response = Stage2ResultsResponse(
        id="job-uuid-123",
        results=[segment]
    )
    assert response.id == "job-uuid-123"
    assert len(response.results) == 1
    assert response.results[0].utterances[0].text == "Ini adalah contoh transkripsi bahasa Indonesia"
    print("✅ Stage2ResultsResponse schema works")
    
    # Test JSON serialization
    json_str = response.model_dump_json(indent=2)
    assert "job-uuid-123" in json_str
    assert "transkripsi" in json_str
    print("✅ JSON serialization works")
    print()
    print("Example JSON output:")
    print(json_str)


def test_multiple_utterances():
    """Test response with multiple utterances per segment."""
    from app.schemas.job import (
        Stage2UtteranceResponse,
        Stage2SegmentResponse,
        Stage2ResultsResponse
    )
    
    utterances = []
    for i in range(3):
        utterance = Stage2UtteranceResponse(
            id=f"transcript-uuid-{i}",
            utterance_index=i,
            text=f"Kalimat ke-{i+1}",
            start=float(i * 4),
            end=float((i + 1) * 4 - 0.5),
            confidence=0.85 + (i * 0.05),
            url=f"/api/v1/assets/jobs/job-uuid/utterances/utterance_0000_{i:04d}.mp4",
            status="cropped"
        )
        utterances.append(utterance)
    
    segment = Stage2SegmentResponse(
        segment_id="segment-uuid",
        asr_review_flag=True,
        utterances=utterances
    )
    
    response = Stage2ResultsResponse(
        id="job-uuid",
        results=[segment]
    )
    
    assert len(response.results[0].utterances) == 3
    assert response.results[0].utterances[1].text == "Kalimat ke-2"
    assert response.results[0].asr_review_flag == True
    print(f"✅ Multiple utterances ({len(utterances)}) per segment works")


def test_multiple_segments():
    """Test response with multiple segments."""
    from app.schemas.job import (
        Stage2UtteranceResponse,
        Stage2SegmentResponse,
        Stage2ResultsResponse
    )
    
    segments = []
    for seg_idx in range(2):
        utterances = []
        for utt_idx in range(2):
            utterance = Stage2UtteranceResponse(
                id=f"transcript-{seg_idx}-{utt_idx}",
                utterance_index=utt_idx,
                text=f"Segmen {seg_idx+1}, Kalimat {utt_idx+1}",
                start=float(utt_idx * 3),
                end=float((utt_idx + 1) * 3 - 0.5),
                confidence=0.9,
                url=f"/api/v1/assets/jobs/job-uuid/utterances/utterance_{seg_idx:04d}_{utt_idx:04d}.mp4",
                status="cropped"
            )
            utterances.append(utterance)
        
        segment = Stage2SegmentResponse(
            segment_id=f"segment-uuid-{seg_idx}",
            asr_review_flag=False,
            utterances=utterances
        )
        segments.append(segment)
    
    response = Stage2ResultsResponse(
        id="job-uuid",
        results=segments
    )
    
    assert len(response.results) == 2
    assert len(response.results[0].utterances) == 2
    assert len(response.results[1].utterances) == 2
    print(f"✅ Multiple segments ({len(segments)}) with utterances works")


def test_empty_utterances():
    """Test segment with no utterances (ASR failed or no speech)."""
    from app.schemas.job import Stage2SegmentResponse, Stage2ResultsResponse
    
    segment = Stage2SegmentResponse(
        segment_id="segment-uuid",
        asr_review_flag=True,
        utterances=[]  # Empty utterances
    )
    
    response = Stage2ResultsResponse(
        id="job-uuid",
        results=[segment]
    )
    
    assert len(response.results[0].utterances) == 0
    assert response.results[0].asr_review_flag == True
    print("✅ Empty utterances array works correctly")


def test_optional_url():
    """Test that URL can be None (video not yet cropped)."""
    from app.schemas.job import Stage2UtteranceResponse
    
    utterance = Stage2UtteranceResponse(
        id="transcript-uuid",
        utterance_index=0,
        text="Contoh teks",
        start=0.0,
        end=2.5,
        confidence=0.88,
        url=None,  # No URL yet
        status="pending"
    )
    
    assert utterance.url is None
    assert utterance.status == "pending"
    print("✅ Optional URL (None) works correctly")


# Example usage documentation
EXAMPLE_USAGE = """
================================================================================
STAGE 2 RESULTS API - EXAMPLE USAGE
================================================================================

1. Get Stage 2 (ASR) Results:
------------------------------
GET /api/v1/pipeline/jobs/{job_id}/stage2/results
Authorization: Bearer <jwt_token>

2. Example Response:
--------------------
{
  "id": "196d54f7-f2c2-4326-ad0e-c3849b8d3d72",
  "results": [
    {
      "segment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "asr_review_flag": false,
      "utterances": [
        {
          "id": "transcript-uuid-1",
          "utterance_index": 0,
          "text": "Ini adalah contoh transkripsi",
          "start": 0.0,
          "end": 3.5,
          "confidence": 0.92,
          "url": "/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/utterances/utterance_0000_0000.mp4",
          "status": "cropped"
        },
        {
          "id": "transcript-uuid-2",
          "utterance_index": 1,
          "text": "Kalimat kedua dari segmen ini",
          "start": 4.0,
          "end": 6.5,
          "confidence": 0.78,
          "url": "/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/utterances/utterance_0000_0001.mp4",
          "status": "cropped"
        }
      ]
    }
  ]
}

3. cURL Example:
----------------
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/pipeline/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/stage2/results

================================================================================
EXPECTED RESPONSES
================================================================================

200 OK - ASR results with utterances list
401 Unauthorized - Missing or invalid JWT token
403 Forbidden - User not authorized to access this job
404 Not Found - Job not found
500 Internal Server Error - Server error

================================================================================
RESPONSE FIELDS
================================================================================

id (string): Job UUID
results (array): List of segments with ASR data
  - segment_id (string): Segment UUID
  - asr_review_flag (boolean): True if segment needs ASR review
  - utterances (array): List of transcribed utterances
    - id (string): Transcript UUID
    - utterance_index (int): Index within segment (0-based)
    - text (string): Transcribed text (Indonesian)
    - start (float): Start time in seconds (relative to segment)
    - end (float): End time in seconds (relative to segment)
    - confidence (float): ASR confidence score (0-1)
    - url (string|null): Asset URL for utterance video
    - status (string): Cropping status - pending, cropped, or failed

================================================================================
DIFFERENCES FROM STAGE 1
================================================================================

Stage 1 (Detection):
  - Returns: bbox_data, segment_url
  - Granularity: Per segment
  - Use case: Visual detection review

Stage 2 (ASR):
  - Returns: utterances[].text, timestamps, confidence
  - Granularity: Per utterance (grouped by segment)
  - Use case: Transcription annotation/correction

================================================================================
"""


if __name__ == "__main__":
    print("=" * 80)
    print("STAGE 2 RESULTS API - BASIC TESTS")
    print("=" * 80)
    print()
    
    tests = [
        test_schema_creation,
        test_multiple_utterances,
        test_multiple_segments,
        test_empty_utterances,
        test_optional_url,
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
