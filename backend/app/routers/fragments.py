from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.models.fragment import Fragment
from app.services import project_service

router = APIRouter(prefix="/api/projects/{project_id}/fragments", tags=["fragments"])


class FragmentUpdate(BaseModel):
    original_text: str | None = None
    image_prompt: str | None = None
    status: str | None = None


@router.get("")
async def list_fragments(project_id: str):
    fragments = await project_service.list_fragments(project_id)
    return {"fragments": [f.model_dump() for f in fragments]}


@router.put("/{fragment_id}")
async def update_fragment(project_id: str, fragment_id: int, body: FragmentUpdate):
    update_data = body.model_dump(exclude_none=True)
    result = await project_service.update_fragment(project_id, fragment_id, update_data)
    if not result:
        raise HTTPException(404, "Fragment not found")
    return {"project_id": project_id, "fragment_id": fragment_id}
