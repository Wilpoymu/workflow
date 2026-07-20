import enum
from pydantic import BaseModel


class ThumbnailMode(str, enum.Enum):
    SINGLE = "single"
    AB_TESTING = "ab_testing"


class ThumbnailRequest(BaseModel):
    script: str
    mode: ThumbnailMode = ThumbnailMode.SINGLE
    variant_count: int = 2
    use_existing_scene: bool = False


class GeminiAnalysis(BaseModel):
    primary_subject: str = ""
    mood_emotion: str = ""
    recommended_colors: dict = {}  # {background: str, text: str, accent: str}
    recommended_text: str = ""  # 3-4 words in Spanish
    composition: str = ""  # Layout suggestion
    background_image_hint: str = ""
    variant_suggestions: list[dict] | None = None


class VariantInfo(BaseModel):
    variant: int
    url: str
    seed: int


class ThumbnailStatus(BaseModel):
    project_id: str
    status: str = "idle"  # idle, analyzing, generating, composing, done, failed
    progress: float = 0.0
    thumbnail_url: str | None = None
    variants: list[VariantInfo] = []
    error: str | None = None
