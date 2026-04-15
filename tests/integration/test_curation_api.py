"""Integration tests for curation API endpoints."""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app
from app.services.auth_service import jwt_auth_service

client = TestClient(app)


def create_token_for_role(role: str) -> str:
    """Helper to create a valid JWT for a specific role."""
    user_id = uuid4()
    return jwt_auth_service.create_access_token(user_id, role)


class TestNormalizeEndpoint:
    """Tests for POST /api/v1/curation/normalize."""

    def test_normalize_without_auth_returns_401(self):
        """Unauthenticated requests are rejected."""
        response = client.post("/api/v1/curation/normalize", json={"items": []})
        assert response.status_code == 401

    def test_normalize_with_annotator_token(self):
        """Annotator can normalize segments."""
        token = create_token_for_role("annotator")
        payload = {
            "items": [
                {"id": "seg-1", "original_text": "Pukul 07:00"},
                {"id": "seg-2", "original_text": "Rp10.000"},
            ]
        }
        response = client.post(
            "/api/v1/curation/normalize",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["normalized_text"] == "pukul tujuh"
        assert data["items"][1]["normalized_text"] == "sepuluh ribu rupiah"

    def test_normalize_with_curator_token(self):
        """Curator can normalize segments."""
        token = create_token_for_role("curator")
        payload = {
            "items": [
                {"id": "seg-1", "original_text": "gak"},
            ]
        }
        response = client.post(
            "/api/v1/curation/normalize",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["normalized_text"] == "tidak"

    def test_normalize_with_sibi_category(self):
        """SIBI category applies extra entity mapping."""
        token = create_token_for_role("annotator")
        payload = {
            "items": [
                {"id": "seg-1", "original_text": "kpk"},
            ]
        }
        response = client.post(
            "/api/v1/curation/normalize?category=SIBI",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["normalized_text"] == "K-P-K"

    def test_normalize_allows_admin(self):
        """Admin is also allowed on the normalize endpoint (superuser)."""
        token = create_token_for_role("admin")
        payload = {"items": [{"id": "seg-1", "original_text": "test"}]}
        response = client.post(
            "/api/v1/curation/normalize",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200


class TestApproveEndpoint:
    """Tests for POST /api/v1/curation/approve."""

    def test_approve_without_auth_returns_401(self):
        """Unauthenticated requests are rejected."""
        response = client.post(
            "/api/v1/curation/approve",
            json={"video_id": str(uuid4())},
        )
        assert response.status_code == 401

    def test_approve_with_annotator_returns_403(self):
        """Annotator cannot approve videos."""
        token = create_token_for_role("annotator")
        response = client.post(
            "/api/v1/curation/approve",
            json={"video_id": str(uuid4())},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @pytest.mark.skip(reason="Requires test PostgreSQL database")
    def test_approve_nonexistent_job_returns_404(self):
        """Curator gets 404 for non-existent job."""
        token = create_token_for_role("curator")
        response = client.post(
            "/api/v1/curation/approve",
            json={"video_id": str(uuid4())},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
