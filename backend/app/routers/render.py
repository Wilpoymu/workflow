import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import project_service
from app.services.kenburns import KenBurnsConfig, render_kenburns_video

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/render", tags=["render"])


class RenderConfig(BaseModel):
    filter_mode: str = "all"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    intensity: float = 0.04
    seed: int = 42
    subtitles: bool = False


class RenderJob:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.ws_connections: dict[str, list[WebSocket]] = {}

    def create_job(self, project_id: str) -> str:
        import uuid
        job_id = uuid.uuid4().hex[:8]
        self.jobs[job_id] = {
            "id": job_id,
            "project_id": project_id,
            "status": "queued",
            "progress": 0,
            "message": "",
            "output_path": None,
        }
        return job_id

    def update_job(self, job_id: str, **kwargs):
        if job_id in self.jobs:
            self.jobs[job_id].update(kwargs)

    def get_job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    async def broadcast(self, project_id: str, data: dict):
        connections = self.ws_connections.get(project_id, [])
        dead = []
        for ws in connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            connections.remove(ws)

    def add_ws(self, project_id: str, ws: WebSocket):
        if project_id not in self.ws_connections:
            self.ws_connections[project_id] = []
        self.ws_connections[project_id].append(ws)

    def remove_ws(self, project_id: str, ws: WebSocket):
        if project_id in self.ws_connections:
            if ws in self.ws_connections[project_id]:
                self.ws_connections[project_id].remove(ws)


render_job = RenderJob()


@router.post("")
async def start_render(
    project_id: str,
    config: RenderConfig = RenderConfig(),
):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    images_dir = Path(project.base_dir) / "imagenes"
    if not images_dir.exists() or not list(images_dir.glob("*.png")):
        raise HTTPException(400, "No images found. Generate images first.")

    job_id = render_job.create_job(project_id)

    kb_config = KenBurnsConfig(
        filter_mode=config.filter_mode,
        width=config.width,
        height=config.height,
        fps=config.fps,
        intensity=config.intensity,
        seed=config.seed,
        subtitles=config.subtitles,
    )

    asyncio.create_task(run_render(job_id, project_id, project.base_dir, kb_config))

    return {"job_id": job_id, "status": "started"}


async def run_render(job_id: str, project_id: str, project_dir: str, config: KenBurnsConfig):
    loop = asyncio.get_event_loop()

    def progress_cb(progress: float, message: str):
        render_job.update_job(job_id, progress=progress, message=message, status="running")
        asyncio.run_coroutine_threadsafe(
            render_job.broadcast(project_id, {
                "type": "progress",
                "job_id": job_id,
                "progress": progress,
                "message": message,
            }),
            loop
        )

    try:
        render_job.update_job(job_id, status="running", progress=0.05, message="Starting render...")
        await render_job.broadcast(project_id, {
            "type": "progress", "job_id": job_id, "progress": 0.05, "message": "Starting render...",
        })

        output_path = await render_kenburns_video(project_dir, config, progress_cb)

        if output_path and output_path.exists():
            render_job.update_job(
                job_id,
                status="done",
                progress=1.0,
                message="Render complete",
                output_path=str(output_path),
            )
            await render_job.broadcast(project_id, {
                "type": "complete",
                "job_id": job_id,
                "output_path": str(output_path),
            })
        else:
            raise RuntimeError("Render failed - no output file created")

    except Exception as e:
        import traceback
        logger.error("Render failed: %s\n%s", e, traceback.format_exc())
        render_job.update_job(job_id, status="failed", message=str(e))
        await render_job.broadcast(project_id, {
            "type": "error",
            "job_id": job_id,
            "message": str(e),
        })


@router.get("")
async def get_render_status(project_id: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    output_dir = Path(project.base_dir) / "render"
    output_path = output_dir / "output.mp4"

    if not output_path.exists():
        return {"has_render": False}

    file_size = output_path.stat().st_size

    return {
        "has_render": True,
        "output_path": str(output_path),
        "file_size": file_size,
        "file_size_mb": round(file_size / 1024 / 1024, 2),
    }


@router.get("/download")
async def download_render(project_id: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    output_dir = Path(project.base_dir) / "render"
    output_path = output_dir / "output.mp4"

    if not output_path.exists():
        raise HTTPException(404, "Render not found. Start a render first.")

    return FileResponse(
        str(output_path),
        media_type="video/mp4",
        filename=f"{project_id}.mp4",
    )


@router.delete("")
async def delete_render(project_id: str):
    """Delete the current render output."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    output_dir = Path(project.base_dir) / "render"
    output_path = output_dir / "output.mp4"

    if output_path.exists():
        output_path.unlink()
        return {"ok": True, "deleted": str(output_path)}
    return {"ok": True, "deleted": None}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await websocket.accept()
    render_job.add_ws(project_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        render_job.remove_ws(project_id, websocket)
