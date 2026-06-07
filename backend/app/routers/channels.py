from fastapi import APIRouter, HTTPException
from app.models.channel import ChannelCreate, ChannelMetadata
from app.services import project_service

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("")
async def list_channels():
    channels = await project_service.list_channels()
    return {"channels": channels}


@router.post("", status_code=201)
async def create_channel(body: ChannelCreate) -> ChannelMetadata:
    return await project_service.create_channel(body)


@router.get("/{channel_id}")
async def get_channel(channel_id: str):
    channels = await project_service.list_channels()
    for ch in channels:
        if ch["id"] == channel_id:
            return ch
    raise HTTPException(404, "Channel not found")


@router.delete("/{channel_id}")
async def delete_channel(channel_id: str):
    ok = await project_service.delete_channel(channel_id)
    if not ok:
        raise HTTPException(404, "Channel not found")
    return {"channel_id": channel_id}


@router.get("/{channel_id}/projects")
async def list_channel_projects(channel_id: str):
    projects = await project_service.list_projects(channel_id)
    return {"projects": projects}
