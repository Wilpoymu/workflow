from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.models.project import ProjectCreate, ProjectMetadata
from app.services import project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ScriptBody(BaseModel):
    text: str


@router.get("/{project_id}/script")
async def get_script(project_id: str):
    text = await project_service.get_script(project_id)
    if text is None:
        raise HTTPException(404, "Script not found")
    return {"text": text, "project_id": project_id}


@router.put("/{project_id}/script")
async def save_script(project_id: str, body: ScriptBody):
    try:
        path = await project_service.save_script(project_id, body.text)
        return {"project_id": project_id, "path": path, "saved": True}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{project_id}/script/fragment")
async def fragment_script(project_id: str, body: ScriptBody | None = None):
    """Run strict-21 fragmentation on script text and save to prompts-*.json.

    Uses existing text.txt content, or accepts text in the request body.
    """
    text = body.text if body else None
    try:
        fragments = await project_service.create_script_fragments(project_id, text)
        return {
            "project_id": project_id,
            "total": len(fragments),
            "fragments": [f.model_dump() for f in fragments],
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


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


# ── Orphaned Project Scanner ──────────────────────────────


@router.post("/scan")
async def scan_orphaned():
    """Scan channel directories for project folders not in the DB.

    Returns a list of candidate projects that exist on disk but
    haven't been indexed. Each entry includes metadata from
    project.json and indicators of what assets exist.
    """
    orphans = await project_service.scan_orphaned_projects()
    return {"orphans": orphans}


class ImportRequest(BaseModel):
    project_id: str
    channel_id: str


@router.post("/import")
async def import_orphan(body: ImportRequest):
    """Import an orphaned project into the DB."""
    try:
        ok = await project_service.import_orphaned_project(
            body.project_id, body.channel_id
        )
        return {"project_id": body.project_id, "imported": ok}
    except ValueError as e:
        raise HTTPException(400, str(e))
