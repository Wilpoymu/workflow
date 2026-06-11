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


FLOW_MODELS = ["NARWHAL", "GEM_PIX_2", "PINHOLE"]

class GenerateRequest(BaseModel):
    concurrency: int = 2
    accounts: list[str] | None = None
    reference_image_ids: list[str] | None = None
    model: str = "NARWHAL"
    fragment_ids: list[int] | None = None
    force: bool = False


class ReferenceInfo(BaseModel):
    name: str
    url: str
    size_kb: float


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
    existing_ids = {img.fragment_id for img in images}
    for f in fragments:
        if not f.image_prompt.strip():
            continue
        if f.fragment_id not in existing_ids:
            # File doesn't exist → report as pending regardless of fragment status
            images.append(ImageInfo(
                fragment_id=f.fragment_id,
                url="",
                status="pending",
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

    # Filter by specific fragment_ids if provided
    if config.fragment_ids:
        pending = [f for f in fragments if f.fragment_id in config.fragment_ids and f.image_prompt.strip()]
    else:
        pending = [f for f in fragments if f.image_prompt.strip()]

    if not pending:
        raise HTTPException(400, "No fragments with prompts to generate")

    # Skip fragments that already have a generated image (unless force)
    if not config.force:
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

    # Load reference images from disk as base64 to upload via extension
    ref_b64_list: list[str] = []
    personaje_dir = Path(project.base_dir) / "personaje"
    if personaje_dir.exists():
        for ref_file in sorted(personaje_dir.glob("*.png")):
            raw = ref_file.read_bytes()
            if len(raw) <= 5 * 1024 * 1024:  # 5MB limit
                ref_b64_list.append(base64.b64encode(raw).decode("ascii"))

    if config.model not in FLOW_MODELS:
        raise HTTPException(400, f"Invalid model '{config.model}'. Valid: {', '.join(FLOW_MODELS)}")

    batch_id = uuid.uuid4().hex[:8]
    total = await bridge.dispatch(
        project_id,
        project.base_dir,
        pending,
        batch_id,
        model=config.model,
        concurrency=config.concurrency,
        selected_accounts=config.accounts,
        reference_image_ids=config.reference_image_ids,
        reference_image_bytes=ref_b64_list if ref_b64_list else None,
    )

    return {"batch_id": batch_id, "total": total, "personaje_images": len(ref_b64_list)}


# ── Reference Images ─────────────────────────────────────

@router.post("/reference")
async def upload_reference_image(project_id: str, request: Request):
    """Upload a reference image for a project (character consistency).

    Saves to project/personaje/ for later upload via extension during generation.
    """
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    personaje_dir = Path(project.base_dir) / "personaje"
    personaje_dir.mkdir(parents=True, exist_ok=True)

    try:
        form = await request.form()
        file = form.get("file")
        if file and hasattr(file, "read"):
            raw_bytes = await file.read()
        else:
            raise HTTPException(400, "No file provided. Send a multipart file field named 'file'.")
    except Exception:
        raise HTTPException(400, "No file provided. Send a multipart file field named 'file'.")

    if not raw_bytes or len(raw_bytes) == 0:
        raise HTTPException(400, "Empty file")
    if len(raw_bytes) > 5 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 5MB)")

    safe_name = f"ref_{uuid.uuid4().hex[:8]}.png"
    local_path = personaje_dir / safe_name
    local_path.write_bytes(raw_bytes)

    await project_service.update_project_meta(project_id, {
        "files": {"personaje": [safe_name]},
    })

    return {
        "ok": True,
        "filename": safe_name,
        "size_kb": round(len(raw_bytes) / 1024, 1),
    }


@router.get("/reference")
async def list_references(project_id: str):
    """List reference images for a project."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    personaje_dir = Path(project.base_dir) / "personaje"
    refs: list[ReferenceInfo] = []
    if personaje_dir.exists():
        for p in sorted(personaje_dir.glob("*.png")):
            refs.append(ReferenceInfo(
                name=p.name,
                url=f"/api/projects/{project_id}/images/reference/file/{p.name}",
                size_kb=round(p.stat().st_size / 1024, 1),
            ))
    return {"references": refs}


@router.get("/reference/file/{filename}")
async def get_reference_file(project_id: str, filename: str):
    """Serve a reference image file."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    path = Path(project.base_dir) / "personaje" / filename
    if not path.exists():
        raise HTTPException(404, "Reference not found")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/reference/{filename}")
async def delete_reference(project_id: str, filename: str):
    """Delete a reference image."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    path = Path(project.base_dir) / "personaje" / filename
    if path.exists():
        path.unlink()
    return {"ok": True, "deleted": filename}


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
