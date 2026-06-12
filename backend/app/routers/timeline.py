"""Timeline CRUD + export endpoints.

Provides:
- GET    /api/projects/{project_id}/timeline       — Load or auto-migrate timeline
- PUT    /api/projects/{project_id}/timeline       — Save timeline
- POST   /api/projects/{project_id}/timeline/export — Export timeline to video
                                                     (SSE progress on project_id channel)

SSE events emitted (on project_id):
  ``timeline_render_progress``  — ``{progress: float, message: str}``
  ``timeline_render_complete``  — ``{output: str}``
  ``timeline_render_error``     — ``{message: str}``
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.sse import sse_manager
from app.services import project_service
from app.services.timeline_migration import auto_migrate
from app.services.timeline_renderer import TimelineRenderer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/timeline", tags=["timeline"])

# ── In-flight export tracking ────────────────────────────────────────────
# Prevents concurrent exports for the same project.
_running_exports: dict[str, asyncio.Task[None]] = {}


# ── Internal helpers ─────────────────────────────────────────────────────


async def _resolve_project(project_id: str) -> str:
    """Return *base_dir* for *project_id* or raise ``404``."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.base_dir


def _sanitize_timeline(obj):
    """Recursively replace NaN/Inf in float fields with 0.0."""
    if isinstance(obj, dict):
        return {k: _sanitize_timeline(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_timeline(v) for v in obj]
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    return obj


def _fix_audio_duration(timeline: dict) -> dict:
    """Ensure audio clip duration > 0 by using video track's total duration."""
    if not isinstance(timeline, dict):
        return timeline
    for track in timeline.get("tracks", []):
        if track.get("type") == "audio":
            for clip in track.get("clips", []):
                dur = clip.get("duration", 0)
                if not isinstance(dur, (int, float)) or dur <= 0 or math.isnan(dur) or math.isinf(dur):
                    # Calculate video track total duration
                    video_dur = 0.0
                    for vt in timeline.get("tracks", []):
                        if vt.get("type") == "video":
                            for vc in vt.get("clips", []):
                                d = vc.get("duration", 0)
                                if isinstance(d, (int, float)) and d > 0:
                                    video_dur += d
                    clip["duration"] = video_dur if video_dur > 0 else 10.0
    return timeline


def _timeline_path(project_dir: str) -> Path:
    return Path(project_dir) / "timeline.json"


async def _load_or_migrate(project_dir: str) -> dict:
    """Load *timeline.json* or auto-migrate from fragments.

    Returns the timeline dict.

    Raises ``HTTPException(404)`` if neither a valid ``timeline.json`` nor
    migratable fragments exist.
    """
    t_path = _timeline_path(project_dir)

    # ── Existing timeline.json — validate and return ────────────────────
    if t_path.exists():
        try:
            data = json.loads(t_path.read_text("utf-8"))
            if isinstance(data, dict) and "tracks" in data:
                return _fix_audio_duration(_sanitize_timeline(data))
            logger.warning("timeline.json exists but is invalid — re-migrating")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("timeline.json corrupt (%s) — re-migrating", exc)

    # ── Auto-migrate from fragment files ────────────────────────────────
    timeline = auto_migrate(project_dir)
    if timeline is None:
        raise HTTPException(
            status_code=404,
            detail="No fragments found. Cannot create timeline.",
        )

    # Persist the migrated result so subsequent GETs are instant
    t_path.write_text(json.dumps(timeline, indent=2), "utf-8")
    logger.info("Auto-migrated timeline from fragments (%d tracks)", len(timeline.get("tracks", [])))
    return timeline


def _make_progress_callback(project_id: str):
    """Build a sync *progress_callback* suitable for ``TimelineRenderer``.

    The returned callable is synchronous (matches ``Callable[[float, str], None]``)
    but schedules each SSE emit as an ``asyncio.Task`` on the current event loop.
    """
    async def _emit(progress: float, message: str) -> None:
        await sse_manager.emit(
            project_id,
            "timeline_render_progress",
            {"progress": progress, "message": message},
        )

    def cb(progress: float, message: str) -> None:
        asyncio.create_task(_emit(progress, message))

    return cb


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("")
async def get_timeline(project_id: str) -> dict:
    """Load the timeline.

    If ``timeline.json`` doesn't exist (or is corrupt), auto-migrate from
    ``prompts-*.json`` fragments and persist the result before returning it.
    """
    project_dir = await _resolve_project(project_id)
    timeline = await _load_or_migrate(project_dir)
    return {"ok": True, "timeline": timeline}


@router.put("")
async def save_timeline(project_id: str, payload: dict) -> dict:
    """Overwrite ``timeline.json`` with the request body."""
    project_dir = await _resolve_project(project_id)
    t_path = _timeline_path(project_dir)
    # Sanitize NaN/Inf before saving
    clean = _fix_audio_duration(_sanitize_timeline(payload))
    t_path.write_text(json.dumps(clean, indent=2), "utf-8")
    logger.info("Timeline saved for project %s (%d bytes)", project_id, t_path.stat().st_size)
    return {"ok": True, "message": "Timeline saved"}


@router.post("/export")
async def export_timeline(project_id: str) -> dict:
    """Render the timeline to an MP4 video.

    The render runs as a background ``asyncio.Task``.  Progress is pushed
    via SSE on the project's event channel.  If an export is already in-flight
    for the same project, a **409 Conflict** is returned.
    """
    # ── Guard: duplicate export ────────────────────────────────────────
    existing = _running_exports.get(project_id)
    if existing is not None and not existing.done():
        raise HTTPException(
            status_code=409,
            detail="An export is already running for this project",
        )

    # ── Resolve project & load / migrate timeline ──────────────────────
    project_dir = await _resolve_project(project_id)
    timeline = await _load_or_migrate(project_dir)

    renderer = TimelineRenderer(project_dir, timeline)
    progress_cb = _make_progress_callback(project_id)

    # ── Background task ────────────────────────────────────────────────
    async def _run_and_notify() -> None:
        try:
            output_path = await renderer.render(progress_callback=progress_cb)
            if output_path:
                await sse_manager.emit(
                    project_id,
                    "timeline_render_complete",
                    {"output": str(output_path)},
                )
                logger.info("Timeline export complete for %s → %s", project_id, output_path)
            else:
                await sse_manager.emit(
                    project_id,
                    "timeline_render_error",
                    {"message": "Render failed — no output produced"},
                )
                logger.error("Timeline export failed for %s (no output)", project_id)
        except Exception as exc:
            logger.exception("Timeline export failed for %s", project_id)
            await sse_manager.emit(
                project_id,
                "timeline_render_error",
                {"message": str(exc)},
            )
        finally:
            _running_exports.pop(project_id, None)

    task = asyncio.create_task(_run_and_notify())
    _running_exports[project_id] = task

    return {"ok": True, "message": "Export started"}
