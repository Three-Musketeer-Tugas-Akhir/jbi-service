"""
Test script for Assets API.

Usage:
    # Run with pytest (if available)
    pytest tests/test_assets_api.py -v

    # Run with Python directly (basic tests)
    python tests/test_assets_api.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from uuid import UUID
from unittest.mock import Mock

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False


# ==============================================================================
# PATH VALIDATION TESTS
# ==============================================================================

def test_validate_path_valid():
    """Test valid path parsing."""
    from app.api.v1.assets import validate_path
    
    path = "jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/original/video.mp4"
    job_id, rel_path = validate_path(path)
    
    assert job_id == UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72")
    assert rel_path == "original/video.mp4"
    print("✅ test_validate_path_valid passed")


def test_validate_path_with_segments():
    """Test path with segments folder."""
    from app.api.v1.assets import validate_path
    
    path = "jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4"
    job_id, rel_path = validate_path(path)
    
    assert job_id == UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72")
    assert rel_path == "segments/segment_0000.mp4"
    print("✅ test_validate_path_with_segments passed")


def test_validate_path_invalid_extension():
    """Test rejection of invalid file extensions."""
    from app.api.v1.assets import validate_path
    
    try:
        validate_path("jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/original/video.exe")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Invalid file type" in str(e)
    print("✅ test_validate_path_invalid_extension passed")


def test_validate_path_traversal():
    """Test path traversal detection."""
    from app.api.v1.assets import validate_path
    
    # Test with .. in path
    try:
        validate_path("jobs/../etc/passwd")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "path traversal" in str(e)
    
    # Test with .. in deeper path
    try:
        validate_path("jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/../../../etc/passwd")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "path traversal" in str(e)
    
    print("✅ test_validate_path_traversal passed")


def test_validate_path_invalid_uuid():
    """Test invalid UUID format."""
    from app.api.v1.assets import validate_path
    
    # Test case 1: Completely invalid format
    try:
        validate_path("jobs/invalid-uuid/original/video.mp4")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        error_msg = str(e)
        assert "Invalid UUID" in error_msg or "Invalid path format" in error_msg
    
    # Test case 2: Wrong UUID format (not matching regex)
    try:
        validate_path("jobs/not-a-uuid/original/video.mp4")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        error_msg = str(e)
        # Should fail the regex pattern match
        assert "Invalid path format" in error_msg
    
    print("✅ test_validate_path_invalid_uuid passed")


def test_validate_path_wrong_format():
    """Test wrong path format."""
    from app.api.v1.assets import validate_path
    
    try:
        validate_path("original/video.mp4")  # Missing jobs/{uuid} prefix
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Invalid path format" in str(e)
    print("✅ test_validate_path_wrong_format passed")


# ==============================================================================
# CONTENT TYPE TESTS
# ==============================================================================

def test_get_content_type_mp4():
    """Test MP4 content type detection."""
    from app.api.v1.assets import get_content_type
    assert get_content_type("video.mp4") == "video/mp4"
    print("✅ test_get_content_type_mp4 passed")


def test_get_content_type_mkv():
    """Test MKV content type detection."""
    from app.api.v1.assets import get_content_type
    assert get_content_type("video.mkv") == "video/x-matroska"
    print("✅ test_get_content_type_mkv passed")


def test_get_content_type_mov():
    """Test MOV content type detection."""
    from app.api.v1.assets import get_content_type
    assert get_content_type("video.mov") == "video/quicktime"
    print("✅ test_get_content_type_mov passed")


def test_get_content_type_json():
    """Test JSON content type detection."""
    from app.api.v1.assets import get_content_type
    assert get_content_type("data.json") == "application/json"
    print("✅ test_get_content_type_json passed")


# ==============================================================================
# AUTHORIZATION TESTS (Async)
# ==============================================================================

async def test_authorize_access_as_owner():
    """Test authorization as job owner."""
    from app.api.v1.assets import authorize_access
    import asyncio
    
    mock_user = Mock()
    mock_user.has_role = Mock(return_value=False)
    mock_user.id = UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72")
    
    mock_job = Mock()
    mock_job.created_by = UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72")
    
    # Create async mock for session
    async def mock_execute(*args, **kwargs):
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_job)
        return mock_result
    
    mock_session = Mock()
    mock_session.execute = mock_execute
    
    result = await authorize_access(mock_user, mock_user.id, mock_session)
    assert result is True
    print("✅ test_authorize_access_as_owner passed")


async def test_authorize_access_as_admin():
    """Test authorization as admin."""
    from app.api.v1.assets import authorize_access
    
    mock_user = Mock()
    mock_user.has_role = Mock(return_value=True)
    
    mock_session = Mock()
    
    result = await authorize_access(mock_user, UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72"), mock_session)
    assert result is True
    print("✅ test_authorize_access_as_admin passed")


async def test_authorize_access_unauthorized():
    """Test authorization denied for non-owner."""
    from app.api.v1.assets import authorize_access
    
    mock_user = Mock()
    mock_user.has_role = Mock(return_value=False)
    mock_user.id = UUID("11111111-1111-1111-1111-111111111111")
    
    mock_job = Mock()
    mock_job.created_by = UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72")
    
    # Create async mock for session
    async def mock_execute(*args, **kwargs):
        mock_result = Mock()
        mock_result.scalar_one_or_none = Mock(return_value=mock_job)
        return mock_result
    
    mock_session = Mock()
    mock_session.execute = mock_execute
    
    result = await authorize_access(mock_user, UUID("196d54f7-f2c2-4326-ad0e-c3849b8d3d72"), mock_session)
    assert result is False
    print("✅ test_authorize_access_unauthorized passed")


# ==============================================================================
# EXAMPLE USAGE
# ==============================================================================

EXAMPLE_USAGE = """
================================================================================
ASSETS API - EXAMPLE USAGE
================================================================================

1. Access original video:
-------------------------
GET /api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/original/video.mp4
Authorization: Bearer <jwt_token>

2. Access segment:
------------------
GET /api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4
Authorization: Bearer <jwt_token>

3. With video seeking (range request):
--------------------------------------
GET /api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/original/video.mp4
Authorization: Bearer <jwt_token>
Range: bytes=0-1048575

4. cURL examples:
-----------------
# Original video
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/original/video.mp4 \
  --output video.mp4

# Segment
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4 \
  --output segment.mp4

# With range (first 1MB)
curl -H "Authorization: Bearer <token>" \
  -H "Range: bytes=0-1048575" \
  http://localhost:8000/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/original/video.mp4

================================================================================
EXPECTED RESPONSES
================================================================================

200 OK - File stream (or 206 Partial Content for range requests)
400 Bad Request - Invalid path format
401 Unauthorized - Missing or invalid JWT token
403 Forbidden - User not authorized to access this job
404 Not Found - File not found in MinIO
500 Internal Server Error - Server error

================================================================================
"""


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    print("=" * 80)
    print("ASSETS API - BASIC TESTS")
    print("=" * 80)
    print()
    
    # Run sync tests
    sync_tests = [
        test_validate_path_valid,
        test_validate_path_with_segments,
        test_validate_path_invalid_extension,
        test_validate_path_traversal,
        test_validate_path_invalid_uuid,
        test_validate_path_wrong_format,
        test_get_content_type_mp4,
        test_get_content_type_mkv,
        test_get_content_type_mov,
        test_get_content_type_json,
    ]
    
    passed = 0
    failed = 0
    
    for test in sync_tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
    
    # Run async tests
    async_tests = [
        test_authorize_access_as_owner,
        test_authorize_access_as_admin,
        test_authorize_access_unauthorized,
    ]
    
    for test in async_tests:
        try:
            asyncio.run(test())
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
