from fastapi import APIRouter, HTTPException
from app.models.project import ProjectCreate, ProjectMetadata
from app.services import project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def list_projects(channel_id: str | None = None):
    projects = await project_service.list_projects(channel_id)
    return {"projects": projects}


@router.post("", status_code=201)
async def create_project(body: ProjectCreate) -> ProjectMetadata:
    try:
        return await project_service.create_project(
            body.name, body.title, body.channel_id or "default"
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}")
async def get_project(project_id: str) -> ProjectMetadata:
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    ok = await project_service.delete_project(project_id)
    if not ok:
        raise HTTPException(404, "Project not found")
    return {"project_id": project_id}
