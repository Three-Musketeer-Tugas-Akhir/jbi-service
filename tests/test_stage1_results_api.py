"""
Test script for Stage 1 Results API.

Usage:
    python tests/test_stage1_results_api.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from uuid import UUID
from unittest.mock import Mock, AsyncMock
import asyncio


def test_schema_creation():
    """Test that schemas can be created correctly."""
    from app.schemas.job import BboxDataResponse, SegmentResultResponse, Stage1ResultsResponse
    
    # Test BboxDataResponse
    bbox = BboxDataResponse(x=100.5, y=200.0, width=300.0, height=150.0)
    assert bbox.x == 100.5
    assert bbox.y == 200.0
    assert bbox.width == 300.0
    assert bbox.height == 150.0
    print("✅ BboxDataResponse schema works")
    
    # Test SegmentResultResponse
    segment = SegmentResultResponse(
        id="segment-uuid-123",
        segment_index=0,
        bbox_data=bbox,
        url="/api/v1/assets/jobs/job-uuid/segments/segment_0000.mp4"
    )
    assert segment.id == "segment-uuid-123"
    assert segment.segment_index == 0
    assert segment.bbox_data.x == 100.5
    assert segment.url == "/api/v1/assets/jobs/job-uuid/segments/segment_0000.mp4"
    print("✅ SegmentResultResponse schema works")
    
    # Test Stage1ResultsResponse
    response = Stage1ResultsResponse(
        id="job-uuid-123",
        results=[segment]
    )
    assert response.id == "job-uuid-123"
    assert len(response.results) == 1
    assert response.results[0].segment_index == 0
    print("✅ Stage1ResultsResponse schema works")
    
    # Test JSON serialization
    json_str = response.model_dump_json(indent=2)
    assert "job-uuid-123" in json_str
    assert "segment_0000.mp4" in json_str
    print("✅ JSON serialization works")
    print()
    print("Example JSON output:")
    print(json_str)


def test_bbox_data_parsing():
    """Test parsing bbox_data from different formats."""
    from app.schemas.job import BboxDataResponse
    
    # Test with various number formats
    test_cases = [
        {"x": 0, "y": 0, "width": 100, "height": 100},
        {"x": 10.5, "y": 20.75, "width": 300.25, "height": 150.5},
        {"x": 100.0, "y": 200.0, "width": 0, "height": 0},  # Edge case: zero dimensions
    ]
    
    for i, data in enumerate(test_cases):
        bbox = BboxDataResponse(**data)
        assert bbox.x == data["x"]
        assert bbox.y == data["y"]
        assert bbox.width == data["width"]
        assert bbox.height == data["height"]
    
    print(f"✅ Parsed {len(test_cases)} different bbox formats")


def test_multiple_segments():
    """Test response with multiple segments."""
    from app.schemas.job import BboxDataResponse, SegmentResultResponse, Stage1ResultsResponse
    
    segments = []
    for i in range(5):
        bbox = BboxDataResponse(
            x=float(i * 100),
            y=float(i * 50),
            width=300.0,
            height=200.0
        )
        segment = SegmentResultResponse(
            id=f"segment-uuid-{i}",
            segment_index=i,
            bbox_data=bbox,
            url=f"/api/v1/assets/jobs/job-uuid/segments/segment_{i:04d}.mp4"
        )
        segments.append(segment)
    
    response = Stage1ResultsResponse(
        id="job-uuid-123",
        results=segments
    )
    
    assert len(response.results) == 5
    assert response.results[2].segment_index == 2
    assert response.results[4].bbox_data.x == 400.0
    print(f"✅ Response with {len(segments)} segments works correctly")


def test_optional_bbox():
    """Test that bbox_data can be None."""
    from app.schemas.job import SegmentResultResponse, Stage1ResultsResponse
    
    segment = SegmentResultResponse(
        id="segment-uuid",
        segment_index=0,
        bbox_data=None,  # No bounding box
        url="/api/v1/assets/jobs/job-uuid/segments/segment_0000.mp4"
    )
    
    response = Stage1ResultsResponse(
        id="job-uuid",
        results=[segment]
    )
    
    assert response.results[0].bbox_data is None
    print("✅ Optional bbox_data (None) works correctly")


# Example usage documentation
EXAMPLE_USAGE = """
================================================================================
STAGE 1 RESULTS API - EXAMPLE USAGE
================================================================================

1. Get Stage 1 Results:
-----------------------
GET /api/v1/pipeline/jobs/{job_id}/stage1/results
Authorization: Bearer <jwt_token>

2. Example Response:
--------------------
{
  "id": "196d54f7-f2c2-4326-ad0e-c3849b8d3d72",
  "results": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "segment_index": 0,
      "bbox_data": {
        "x": 100.5,
        "y": 200.0,
        "width": 300.0,
        "height": 150.0
      },
      "url": "/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4"
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
      "segment_index": 1,
      "bbox_data": {
        "x": 150.0,
        "y": 250.0,
        "width": 320.0,
        "height": 180.0
      },
      "url": "/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0001.mp4"
    }
  ]
}

3. cURL Example:
----------------
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/pipeline/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/stage1/results

================================================================================
EXPECTED RESPONSES
================================================================================

200 OK - Stage 1 results with segments list
401 Unauthorized - Missing or invalid JWT token
403 Forbidden - User not authorized to access this job
404 Not Found - Job not found
500 Internal Server Error - Server error

================================================================================
RESPONSE FIELDS
================================================================================

id (string): Job UUID
results (array): List of segment results
  - id (string): Segment UUID
  - segment_index (int): Segment index (0-based)
  - bbox_data (object|null): Bounding box coordinates
    - x (float): X coordinate (top-left)
    - y (float): Y coordinate (top-left)
    - width (float): Bounding box width
    - height (float): Bounding box height
  - url (string): Asset URL for accessing the segment video

================================================================================
"""


if __name__ == "__main__":
    print("=" * 80)
    print("STAGE 1 RESULTS API - BASIC TESTS")
    print("=" * 80)
    print()
    
    tests = [
        test_schema_creation,
        test_bbox_data_parsing,
        test_multiple_segments,
        test_optional_bbox,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
    
    print()
    print("=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 80)
    print()
    print(EXAMPLE_USAGE)
