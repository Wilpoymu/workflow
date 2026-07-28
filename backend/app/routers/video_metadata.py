from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from app.routers.shorts import _resolve_project_dir
from app.services import video_metadata_service

router = APIRouter(prefix="/api/projects/{project_id}/metadata/video", tags=["metadata"])


class GenerateMetadataRequest(BaseModel):
    text: str


@router.post("/generate")
async def generate_metadata(project_id: str, body: GenerateMetadataRequest):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    try:
        result = await video_metadata_service.generate_and_save(
            project_id, project_dir, body.text
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def get_metadata(project_id: str):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    result = await video_metadata_service.get_metadata(project_id, project_dir)
    if result is None:
        return {"metadata": None}
    return {"metadata": result}


@router.put("")
async def update_metadata(project_id: str, body: dict[str, Any]):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    try:
        result = await video_metadata_service.save_metadata(
            project_id, project_dir, body
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate-chapters")
async def validate_chapters(project_id: str):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    try:
        result = await video_metadata_service.validate_chapters(project_id, project_dir)
        if result is None:
            raise HTTPException(status_code=404, detail="No metadata found to validate")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
