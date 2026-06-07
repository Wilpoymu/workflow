from datetime import datetime
from pydantic import BaseModel


class ProjectFiles(BaseModel):
    prompts: str = ""
    audio: str = ""
    images_dir: str = "imagenes"
    thumbnail: str = ""
    video: str = ""


class ProjectStats(BaseModel):
    prompts_total: int = 0
    images_generated: int = 0
    images_failed: int = 0


class HistoryEntry(BaseModel):
    batch_id: str
    total: int
    done: int
    failed: int
    model: str
    accounts: list[str]
    concurrency: int
    timestamp: str


class ProjectMetadata(BaseModel):
    name: str
    title: str
    created: str = ""
    status: str = "editing"
    base_dir: str = ""
    files: ProjectFiles = ProjectFiles()
    stats: ProjectStats = ProjectStats()
    history: list[HistoryEntry] = []


class ProjectCreate(BaseModel):
    name: str
    title: str = ""
    channel_id: str | None = None
