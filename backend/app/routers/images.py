import asyncio
import base64
import json
import logging
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.core.sse import sse_manager
from app.models.image import ImageInfo
from app.services import project_service
from app.services.forge_bridge import bridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["images"])


class GenerateRequest(BaseModel):
    concurrency: int = 2
    accounts: list[str] | None = None


async def save_image(project_id: str, fragment_id: int, data: dict):
    project = await project_service.get_project(project_id)
    if not project:
        logger.warning("[SAVE] Project %s not found", project_id)
        return
    img_dir = Path(project.base_dir) / "imagenes"
    img_dir.mkdir(parents=True, exist_ok=True)

    logger.info("[SAVE] save_image fragment=%d data keys=%s", fragment_id, list(data.keys()) if isinstance(data, dict) else type(data).__name__)

    fife_url = None
    try:
        media_list = data.get("media", [])
        if media_list and isinstance(media_list, list):
            first = media_list[0]
            img = first.get("image", {})
            gen = img.get("generatedImage", {})
            fife_url = gen.get("fifeUrl")
    except Exception as e:
        logger.warning("[SAVE] Error parsing Flow response: %s", e)

    if fife_url:
        try:
            path = img_dir / f"escena_{fragment_id:03d}.png"
            async with httpx.AsyncClient() as client:
                resp = await client.get(fife_url, timeout=60)
                resp.raise_for_status()
                path.write_bytes(resp.content)
            logger.info("[SAVE] Downloaded from fifeUrl fragment=%d size=%d bytes", fragment_id, len(resp.content))
            status = "done"
        except Exception as e:
            logger.warning("[SAVE] Failed to download from fifeUrl: %s", e)
            status = "failed"
    else:
        logger.warning("[SAVE] No fifeUrl found for fragment=%d, data=%s", fragment_id, json.dumps(data)[:500])
        status = "failed"

    await project_service.update_fragment(
        project_id, fragment_id,
        {"status": status},
    )


@router.get("")
async def list_images(project_id: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    img_dir = Path(project.base_dir) / "imagenes"
    images: list[ImageInfo] = []

    if img_dir.exists():
        for p in sorted(img_dir.glob("escena_*.png")):
            fid = int(p.stem.split("_")[1])
            images.append(ImageInfo(
                fragment_id=fid,
                url=f"/api/projects/{project_id}/images/file/{p.name}",
                status="done",
            ))

    fragments = await project_service.list_fragments(project_id)
    existing = {img.fragment_id for img in images}
    for f in fragments:
        if f.fragment_id not in existing and f.image_prompt.strip():
            images.append(ImageInfo(
                fragment_id=f.fragment_id,
                url="",
                status=f.status if f.status else "pending",
            ))

    return {"images": sorted(images, key=lambda x: x.fragment_id)}


@router.get("/file/{filename}")
async def get_image_file(project_id: str, filename: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    path = Path(project.base_dir) / "imagenes" / filename
    if not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(path), media_type="image/png")


@router.get("/accounts")
async def list_accounts():
    """List connected Forge accounts"""
    return {"accounts": bridge.get_accounts()}


@router.post("/generate")
async def generate_images(project_id: str, config: GenerateRequest = GenerateRequest()):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    fragments = await project_service.list_fragments(project_id)
    pending = [f for f in fragments if f.image_prompt.strip()]
    if not pending:
        raise HTTPException(400, "No fragments with prompts to generate")

    # Skip fragments that already have a generated image
    img_dir = Path(project.base_dir) / "imagenes"
    existing_ids: set[int] = set()
    if img_dir.exists():
        for p in img_dir.glob("escena_*.png"):
            try:
                fid = int(p.stem.split("_")[1])
                existing_ids.add(fid)
            except (IndexError, ValueError):
                pass

    if existing_ids:
        logger.info("[GENERATE] %d images already exist, skipping them", len(existing_ids))
        pending = [f for f in pending if f.fragment_id not in existing_ids]

    if not pending:
        return {"batch_id": "", "total": 0, "message": "All fragments already have images"}

    batch_id = uuid.uuid4().hex[:8]
    total = await bridge.dispatch(
        project_id,
        project.base_dir,
        pending,
        batch_id,
        concurrency=config.concurrency,
        selected_accounts=config.accounts,
    )

    return {"batch_id": batch_id, "total": total}


@router.get("/events")
async def image_events(request: Request, project_id: str):
    queue = sse_manager.subscribe(project_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_manager.unsubscribe(project_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
