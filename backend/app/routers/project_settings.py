import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import project_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    settings: dict


@router.get("")
async def get_settings(project_id: str):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {"project_id": project_id, "settings": project.settings}


@router.put("")
async def update_settings(project_id: str, body: SettingsUpdate):
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    existing = dict(project.settings)
    for key, value in body.settings.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key] = {**existing[key], **value}
        else:
            existing[key] = value

    await project_service.update_project_meta(project_id, {"settings": existing})
    return {"project_id": project_id, "settings": existing, "saved": True}
