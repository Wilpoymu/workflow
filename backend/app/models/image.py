from pydantic import BaseModel


class GenerateRequest(BaseModel):
    model: str = "sd3.5"
    concurrency: int = 2


class GenerateResult(BaseModel):
    fragment_id: int
    status: str = "pending"
    url: str = ""
    error: str = ""


class BatchStatus(BaseModel):
    batch_id: str
    total: int
    done: int
    failed: int
    model: str


class ImageInfo(BaseModel):
    fragment_id: int
    url: str
    status: str
