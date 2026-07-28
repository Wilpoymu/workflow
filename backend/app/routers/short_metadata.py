from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routers.shorts import _resolve_project_dir
from app.services.shorts_metadata_service import generate_metadata as _generate

router = APIRouter(prefix="/api/projects/{project_id}/shorts/metadata", tags=["shorts"])


class MetadataRequest(BaseModel):
    text: str
    platform: str = "both"


@router.post("")
async def generate_metadata(project_id: str, body: MetadataRequest):
    project_dir = await _resolve_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    if body.platform not in ("both", "tiktok", "youtube"):
        raise HTTPException(status_code=400, detail="Platform must be 'both', 'tiktok', or 'youtube'")

    try:
        result = await _generate(text=body.text, platform=body.platform)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
