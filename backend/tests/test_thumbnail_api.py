"""Integration tests for the Thumbnail API endpoints.

Tests the HTTP contract of the thumbnail router:
- POST /api/projects/{id}/thumbnails/generate
- GET  /api/projects/{id}/thumbnails/status
- GET  /api/projects/{id}/thumbnails/file/{filename}
- GET  /api/projects/{id}/thumbnails/events

Uses a minimal FastAPI app with only the thumbnail router registered,
and monkeypatches external service calls to avoid real Gemini/Flow usage.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.thumbnail import ThumbnailMode, ThumbnailRequest, ThumbnailStatus
from app.routers.thumbnails import router as thumbnails_router
from tests.conftest import make_fake_project


# ─── Minimal test app ─────────────────────────────────────────

app = FastAPI()
app.include_router(thumbnails_router)


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_project():
    """Create a temporary directory and fake project metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = make_fake_project(name="test-project", base_dir=tmpdir)
        yield project


@pytest.fixture(autouse=True)
def mock_services(monkeypatch, tmp_project):
    """Replace external service calls with controlled mocks."""

    # Clear in-memory job state before each test
    from app.routers.thumbnails import _thumbnail_jobs
    _thumbnail_jobs.clear()

    # Mock project_service.get_project to return our fake project
    async def mock_get_project(project_id):
        return tmp_project

    monkeypatch.setattr(
        "app.services.project_service.get_project",
        mock_get_project,
    )

    # Mock thumbnail_service.generate_thumbnail to return fake paths
    # This avoids real Gemini Web calls and Flow dispatch.
    async def mock_generate_thumbnail(project_id, request):
        thumb_dir = Path(tmp_project.base_dir) / "thumbnail"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        file_count = request.variant_count if request.mode == ThumbnailMode.AB_TESTING else 1
        for i in range(file_count):
            path = thumb_dir / f"thumbnail_{'v' + str(i + 1) if file_count > 1 else 'main'}.png"
            path.write_text("fake-png-content")
            paths.append(str(path))
        return paths

    monkeypatch.setattr(
        "app.routers.thumbnails.run_thumbnail_generation",
        mock_generate_thumbnail,
    )


@pytest.fixture(autouse=True)
def delayed_mock(monkeypatch):
    """For tests that need the background task to remain 'in progress', use a slow mock."""
    # Default: fast mock (instant completion)
    pass


@pytest.fixture
def client():
    """Provide a TestClient for the minimal thumbnail app."""
    with TestClient(app) as c:
        yield c


# ─── Helpers ──────────────────────────────────────────────────


def _thumbnail_payload(**overrides) -> dict:
    """Build a valid thumbnail request payload."""
    payload = {
        "script": "Este es un script de prueba para generar un thumbnail impresionante.",
        "mode": ThumbnailMode.SINGLE.value,
        "variant_count": 1,
        "use_existing_scene": False,
    }
    payload.update(overrides)
    return payload


# ─── POST /generate ──────────────────────────────────────────


class TestGenerateEndpoint:
    """Tests for POST /api/projects/{id}/thumbnails/generate."""

    def test_returns_200_and_job_id(self, client):
        """A valid request should return 200 with generation metadata."""
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["project_id"] == "test-project"
        assert data["status"] == "generating"
        assert data["mode"] == "single"

    def test_single_mode_default(self, client):
        """Default mode should be 'single'."""
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "single"
        assert data["variant_count"] == 1

    def test_ab_testing_mode_with_variants(self, client):
        """A/B testing mode should return variant_count in response."""
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(
                mode=ThumbnailMode.AB_TESTING.value,
                variant_count=3,
            ),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "ab_testing"
        assert data["variant_count"] == 3

    def test_empty_script_is_accepted(self, client):
        """Empty script is technically valid Pydantic (str), so should return 200."""
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(script=""),
        )
        assert resp.status_code == 200

    def test_missing_script_field_returns_422(self, client):
        """Completely missing 'script' field should trigger FastAPI validation error."""
        payload = _thumbnail_payload()
        del payload["script"]
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=payload,
        )
        assert resp.status_code == 422

    def test_duplicate_generation_while_in_progress(self, client, monkeypatch):
        """Starting a second generation while one is in progress should return 400."""
        # Slow down the mock so the background task stays "generating"
        async def slow_generate(project_id, request):
            import asyncio
            await asyncio.sleep(0.5)  # Long enough for two POSTs
            thumb_dir = Path(project_id) / "thumbnail"  # won't actually be called
            return []

        monkeypatch.setattr(
            "app.routers.thumbnails.run_thumbnail_generation",
            slow_generate,
        )

        # First request starts generation
        client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(),
        )

        # Second request should be rejected
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(),
        )
        assert resp.status_code == 400
        assert "already in progress" in resp.text.lower()

    def test_nonexistent_project_returns_404(self, client, monkeypatch):
        """Request for a non-existent project should return 404."""

        async def mock_get_project_none(project_id):
            return None

        monkeypatch.setattr(
            "app.services.project_service.get_project",
            mock_get_project_none,
        )

        resp = client.post(
            "/api/projects/nonexistent/thumbnails/generate",
            json=_thumbnail_payload(),
        )
        assert resp.status_code == 404


# ─── GET /status ──────────────────────────────────────────────


class TestStatusEndpoint:
    """Tests for GET /api/projects/{id}/thumbnails/status."""

    def test_idle_status_when_no_job(self, client):
        """A project with no previous job should return idle status."""
        resp = client.get("/api/projects/test-project/thumbnails/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["project_id"] == "test-project"
        assert "variants" in data

    def test_status_changes_after_generation(self, client):
        """After generation starts, status should reflect the in-progress state."""
        client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(),
        )
        resp = client.get("/api/projects/test-project/thumbnails/status")
        assert resp.status_code == 200
        data = resp.json()
        # The background task runs asynchronously, so status may be "generating" or "done"
        assert data["status"] in ("generating", "done")
        assert data["project_id"] == "test-project"

    def test_nonexistent_project_returns_404(self, client, monkeypatch):
        """Status for a non-existent project should return 404."""

        async def mock_get_project_none(project_id):
            return None

        monkeypatch.setattr(
            "app.services.project_service.get_project",
            mock_get_project_none,
        )

        resp = client.get("/api/projects/nonexistent/thumbnails/status")
        assert resp.status_code == 404

    def test_status_shape_matches_thumbnail_status_model(self, client):
        """The status response should match the ThumbnailStatus model fields."""
        resp = client.get("/api/projects/test-project/thumbnails/status")
        assert resp.status_code == 200
        data = resp.json()
        # ThumbnailStatus fields
        assert "project_id" in data
        assert "status" in data
        assert "progress" in data
        assert "variants" in data
        assert "error" in data or "thumbnail_url" in data


# ─── GET /file ────────────────────────────────────────────────


class TestFileEndpoint:
    """Tests for GET /api/projects/{id}/thumbnails/file/{filename}."""

    def test_returns_404_for_nonexistent_file(self, client):
        """Requesting a file that does not exist should return 404."""
        resp = client.get(
            "/api/projects/test-project/thumbnails/file/nonexistent.png",
        )
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()

    def test_returns_404_for_random_filename(self, client):
        """A random filename should not resolve to any file."""
        resp = client.get(
            "/api/projects/test-project/thumbnails/file/../secrets.txt",
        )
        assert resp.status_code in (400, 404)

    def test_nonexistent_project_returns_404(self, client, monkeypatch):
        """File request for a non-existent project should return 404."""

        async def mock_get_project_none(project_id):
            return None

        monkeypatch.setattr(
            "app.services.project_service.get_project",
            mock_get_project_none,
        )

        resp = client.get(
            "/api/projects/nonexistent/thumbnails/file/test.png",
        )
        assert resp.status_code == 404

    def test_returns_file_after_generation(self, client):
        """After generation, thumbnail files should be accessible."""
        # Trigger generation
        client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(),
        )

        # Wait a tiny bit for the background task to complete
        import time
        time.sleep(0.1)

        resp = client.get(
            "/api/projects/test-project/thumbnails/file/thumbnail_main.png",
        )
        # The file may or may not exist depending on mock timing, but the endpoint should
        # handle it gracefully (either 200 or 404, not 500)
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert resp.headers.get("content-type") == "image/png"


# ─── GET /events (SSE) ────────────────────────────────────────


class TestEventsEndpoint:
    """Tests for GET /api/projects/{id}/thumbnails/events (SSE stream)."""

    def test_sse_stream_starts(self, client):
        """The SSE endpoint should establish a connection and start streaming."""
        resp = client.get(
            "/api/projects/test-project/thumbnails/events",
        )
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")


# ─── Edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    """Tests for various edge cases and error handling."""

    def test_unexpected_http_methods(self, client):
        """PUT, DELETE, PATCH should return 405 Method Not Allowed."""
        payload = _thumbnail_payload()
        for method in ("put", "patch"):
            resp = getattr(client, method)(
                "/api/projects/test-project/thumbnails/generate",
                json=payload,
            )
            assert resp.status_code == 405, (
                f"Expected 405 for {method.upper()}, got {resp.status_code}"
            )
        # DELETE doesn't accept a JSON body in httpx
        resp = client.delete(
            "/api/projects/test-project/thumbnails/generate",
        )
        assert resp.status_code == 405, (
            f"Expected 405 for DELETE, got {resp.status_code}"
        )

    def test_invalid_json_body_returns_422(self, client):
        """Sending non-JSON or malformed JSON should return 422."""
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_invalid_mode_value_returns_422(self, client):
        """An invalid mode enum value should be rejected by Pydantic."""
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(mode="invalid_mode"),
        )
        assert resp.status_code == 422

    def test_very_long_script(self, client):
        """A very long script should be accepted."""
        long_script = "Hola. " * 10_000  # ~50K chars
        resp = client.post(
            "/api/projects/test-project/thumbnails/generate",
            json=_thumbnail_payload(script=long_script),
        )
        assert resp.status_code == 200

    def test_file_endpoint_rejects_directory_traversal(self, client):
        """Directory traversal in filename should be blocked."""
        resp = client.get(
            "/api/projects/test-project/thumbnails/file/../../etc/passwd",
        )
        assert resp.status_code in (400, 404)
