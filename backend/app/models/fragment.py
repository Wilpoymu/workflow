from pydantic import BaseModel


class Fragment(BaseModel):
    fragment_id: int
    original_text: str
    image_prompt: str = ""
    source: str = "ai"
    status: str = "pending"
    provider: str = ""
    model: str = ""
    updatedAt: str = ""
    start_time: float | None = None
    end_time: float | None = None


class PromptMap(BaseModel):
    items: dict[str, str] = {}
