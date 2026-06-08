from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SrtEntry:
    index: int
    start_sec: float
    end_sec: float
    text: str

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class ClipSuggestion:
    start_sec: float
    end_sec: float
    score: float
    reason: str
    text_preview: str
    srt_entries: list[SrtEntry] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class ProjectInput:
    video_path: Path
    srt_path: Path | None = None
    script_path: Path | None = None
    prompts_path: Path | None = None
    output_dir: Path = Path("output")


@dataclass
class RenderJob:
    suggestion: ClipSuggestion
    video_path: Path
    srt_path: Path | None
    output_path: Path
    width: int = 1080
    height: int = 1920
    font_size: int = 52
    font_color: str = "white"
    outline_color: str = "black"
    outline_width: int = 3
    bg_enabled: bool = True
    shadow_distance: int = 2
    letter_spacing: float = 1.2
