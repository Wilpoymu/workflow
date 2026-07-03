"""
Thumbnail router — Endpoints for thumbnail generation, status, SSE events, and file serving.

Follows the same patterns as images.py for consistency:
- SSE via sse_manager.subscribe() / .emit()
- File serving via FileResponse
- Background generation via asyncio.create_task
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.core.sse import sse_manager
from app.models.thumbnail import ThumbnailMode, ThumbnailRequest, ThumbnailStatus, VariantInfo
from app.services import project_service
from app.services.thumbnail_service import generate_thumbnail as run_thumbnail_generation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/thumbnails", tags=["thumbnails"])

# ─── In-memory job tracking ──────────────────────────────────

_thumbnail_jobs: dict[str, dict] = {}


def _get_job(project_id: str) -> dict:
    """Get or create a default job entry for a project."""
    if project_id not in _thumbnail_jobs:
        _thumbnail_jobs[project_id] = {
            "status": "idle",
            "progress": 0.0,
            "error": None,
            "output_paths": [],
        }
    return _thumbnail_jobs[project_id]


# ─── Background job runner ───────────────────────────────────


async def _run_thumbnail_job(project_id: str, request: ThumbnailRequest):
    """Execute thumbnail generation in the background and update job state.

    Emits thumbnail_progress / thumbnail_complete / thumbnail_failed SSE events.
    """
    job = _thumbnail_jobs.get(project_id)
    if not job:
        logger.warning("[THUMBNAIL] Job state missing for %s — creating new", project_id)
        job = _get_job(project_id)

    try:
        paths = await run_thumbnail_generation(project_id, request)
        job.update({
            "status": "done" if paths else "failed",
            "progress": 1.0,
            "output_paths": paths,
            "error": None if paths else "No thumbnails were generated",
        })
        if not paths:
            await sse_manager.emit(project_id, "thumbnail_failed", {
                "error": "No thumbnails were generated",
            })
    except Exception as e:
        logger.error("[THUMBNAIL] Generation failed for project %s: %s", project_id, e)
        job.update({
            "status": "failed",
            "error": str(e),
        })
        await sse_manager.emit(project_id, "thumbnail_failed", {"error": str(e)})


# ─── Endpoints ────────────────────────────────────────────────


@router.post("/generate")
async def generate_thumbnail(project_id: str, request: ThumbnailRequest):
    """Start thumbnail generation in the background.

    Accepts script text, generation mode (single / ab), and variant count.
    Returns immediately. Progress is available via GET /status and SSE /events.
    """
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    job = _get_job(project_id)
    if job["status"] == "generating":
        raise HTTPException(400, "Thumbnail generation already in progress")

    # Reset and launch
    job.update({
        "status": "generating",
        "progress": 0.0,
        "error": None,
        "output_paths": [],
    })

    asyncio.create_task(_run_thumbnail_job(project_id, request))

    return {
        "project_id": project_id,
        "status": "generating",
        "mode": request.mode.value,
        "variant_count": request.variant_count,
    }


@router.get("/status")
async def get_thumbnail_status(project_id: str):
    """Return the current thumbnail generation status for a project."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    job = _thumbnail_jobs.get(project_id)

    if job:
        variants = [
            VariantInfo(
                variant=i,
                url=f"/api/projects/{project_id}/thumbnails/file/{Path(p).name}",
                seed=0,
            )
            for i, p in enumerate(job.get("output_paths", []))
        ]
        return ThumbnailStatus(
            project_id=project_id,
            status=job.get("status", "idle"),
            progress=job.get("progress", 0.0),
            variants=variants,
            error=job.get("error"),
        )

    # No job tracked — check if files exist on disk
    thumb_dir = Path(project.base_dir) / "thumbnail"
    existing = sorted(thumb_dir.glob("thumbnail*.png")) if thumb_dir.exists() else []
    if existing:
        variants = [
            VariantInfo(variant=i, url=f"/api/projects/{project_id}/thumbnails/file/{p.name}", seed=0)
            for i, p in enumerate(existing)
        ]
        return ThumbnailStatus(
            project_id=project_id,
            status="done",
            progress=1.0,
            variants=variants,
        )

    return ThumbnailStatus(project_id=project_id, status="idle")


@router.get("/file/{filename}")
async def get_thumbnail_file(project_id: str, filename: str):
    """Serve a generated thumbnail PNG file."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    path = Path(project.base_dir) / "thumbnail" / filename
    # Prevent directory traversal
    resolved = path.resolve()
    allowed = Path(project.base_dir).resolve()
    if not str(resolved).startswith(str(allowed)):
        raise HTTPException(400, "Invalid filename")

    if not path.exists():
        raise HTTPException(404, "Thumbnail not found")

    return FileResponse(str(path), media_type="image/png")


@router.get("/events")
async def thumbnail_events(request: Request, project_id: str):
    """SSE endpoint for real-time thumbnail generation progress.

    Events:
    - thumbnail_progress: { status, progress, message }
    - thumbnail_complete: { variants: [{ variant, url, seed }] }
    - thumbnail_failed:   { error }
    """
    queue = sse_manager.subscribe(project_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=15)
                    if event_type.startswith("thumbnail_"):
                        yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_manager.unsubscribe(project_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
