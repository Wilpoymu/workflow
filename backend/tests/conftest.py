"""Shared test fixtures and configuration for thumbnail tests."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.models.project import ProjectFiles, ProjectMetadata
from app.models.thumbnail import GeminiAnalysis


# ─── Helper factories ─────────────────────────────────────────


def make_fake_project(name: str = "test-project", base_dir: str | None = None) -> ProjectMetadata:
    """Create a fake ProjectMetadata for use in API tests."""
    if base_dir is None:
        base_dir = str(Path(tempfile.gettempdir()) / "thumbnail-test" / name)
    return ProjectMetadata(
        name=name,
        title="Test Project",
        base_dir=base_dir,
        files=ProjectFiles(thumbnail=""),
        status="editing",
    )


def make_minimal_analysis(**overrides) -> GeminiAnalysis:
    """Create a GeminiAnalysis with sensible defaults for Pillow composition tests.

    Uses a defaults-dict approach so that callers overriding a field (e.g.
    ``make_minimal_analysis(recommended_text="...")``) don't get a duplicate
    keyword error — the override simply replaces the default.
    """
    defaults = dict(
        primary_subject="a person standing in a dramatic landscape",
        mood_emotion="dramatic, epic",
        recommended_colors={
            "background": "#1a1a2e",
            "text": "#FFFFFF",
            "accent": "#e94560",
        },
        recommended_text="¡Mira esto!",
        composition="lower_third",
        background_image_hint=(
            "A dramatic landscape with storm clouds and golden light, "
            "cinematic composition"
        ),
    )
    defaults.update(overrides)
    return GeminiAnalysis(**defaults)


# ─── pytest-asyncio support ───────────────────────────────────


@pytest.fixture
def event_loop():
    """Provide an event loop for async tests."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
