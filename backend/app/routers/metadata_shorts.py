from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routers.shorts import _resolve_project_dir
from app.services import shorts_metadata_service

router = APIRouter(prefix="/api/projects/{project_id}/metadata/shorts", tags=["metadata"])


class GenerateShortsMetadataRequest(BaseModel):
    index: str
    text: str
    platform: str = "both"


@router.post("/generate")
async def generate_metadata(project_id: str, body: GenerateShortsMetadataRequest):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")
    if body.platform not in ("both", "tiktok", "youtube"):
        raise HTTPException(status_code=400, detail="Platform must be 'both', 'tiktok', or 'youtube'")

    try:
        result = await shorts_metadata_service.generate_and_save(
            project_dir, body.text, body.index, body.platform
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def get_metadata(project_id: str, index: str | None = None):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    result = await shorts_metadata_service.get_metadata(project_dir, index)
    return {"metadata": result}
