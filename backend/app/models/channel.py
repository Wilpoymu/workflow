from datetime import datetime
from pydantic import BaseModel
from pathlib import Path


class ChannelCreate(BaseModel):
    name: str
    base_path: str


class ChannelMetadata(BaseModel):
    id: str
    name: str
    base_path: str
    created_at: str
    updated_at: str


def make_channel_id(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-")
