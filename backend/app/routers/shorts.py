import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import project_service
from app.services.shorts_maker.analyzer import analyze_folder, find_video_in_folder
from app.services.shorts_maker.clipper import render_job
from app.services.shorts_maker.types import ClipSuggestion, RenderJob

router = APIRouter(prefix="/api/projects/{project_id}/shorts", tags=["shorts"])


class ManualClip(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    duration: float
    reason: str = "manual"
    text_preview: str = ""
    start_word_idx: int | None = None
    end_word_idx: int | None = None


class RenderRequest(BaseModel):
    selections: list[int]
    font_size: int = 52
    with_subtitles: bool = True
    manual_clips: list[ManualClip] = []


class AnalyzeResponse(BaseModel):
    suggestions: list[dict]


class RenderResult(BaseModel):
    index: int
    filename: str
    success: bool
    error: str | None = None


class RenderResponse(BaseModel):
    results: list[RenderResult]


class DownloadItem(BaseModel):
    filename: str
    size_bytes: int


class DownloadsResponse(BaseModel):
    files: list[DownloadItem]


async def _resolve_project_dir(project_id: str) -> Path:
    """Resolve project directory from project_id."""
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return Path(project.base_dir)


def _build_srt_from_words(project_dir: Path, start_idx: int, end_idx: int) -> Path | None:
    """Build a temporary SRT file from word timestamps for precise subtitle tracking."""
    for candidate in (project_dir / "audio" / "script.json", project_dir / "script.json"):
        if candidate.exists():
            break
    else:
        return None

    data = json.loads(candidate.read_text(encoding="utf-8"))
    if isinstance(data, list):
        words = data[0].get("words", []) if data else []
    else:
        words = data.get("words", [])

    word_entries = [w for w in words if w.get("type") == "word"]
    selected = word_entries[start_idx:end_idx + 1]
    if not selected:
        return None

    def _fmt_srt(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    # Group into subtitle blocks of ~5 words each
    blocks: list[list[dict]] = []
    block_size = 5
    for i in range(0, len(selected), block_size):
        blocks.append(selected[i:i + block_size])

    lines: list[str] = []
    for bi, block in enumerate(blocks, 1):
        text = " ".join(w["text"] for w in block)
        start = block[0]["start"]
        end = block[-1]["end"]
        lines.append(str(bi))
        lines.append(f"{_fmt_srt(start)} --> {_fmt_srt(end)}")
        lines.append(text)
        lines.append("")

    temp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=f"_{start_idx}_{end_idx}.srt",
        delete=False,
        encoding="utf-8",
    )
    temp.write("\n".join(lines))
    temp.close()
    return Path(temp.name)


@router.post("/analyze")
async def analyze_project(project_id: str) -> AnalyzeResponse:
    """Analyze project folder and suggest best moments for shorts."""
    project_dir = await _resolve_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project directory not found: {project_dir}",
        )

    try:
        suggestions = analyze_folder(project_dir)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze project: {e}",
        )

    return AnalyzeResponse(
        suggestions=[
            {
                "index": i,
                "start_sec": s.start_sec,
                "end_sec": s.end_sec,
                "duration": s.duration,
                "score": s.score,
                "reason": s.reason,
                "text_preview": s.text_preview,
            }
            for i, s in enumerate(suggestions)
        ]
    )


@router.post("/render")
async def render_shorts(project_id: str, body: RenderRequest) -> RenderResponse:
    """Render selected shorts for the project."""
    project_dir = await _resolve_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project directory not found: {project_dir}",
        )

    video_path = find_video_in_folder(project_dir)
    if not video_path:
        raise HTTPException(
            status_code=400,
            detail="No video found in project directory",
        )

    srt_files = list(project_dir.glob("*.srt"))
    if not srt_files:
        audio_dir = project_dir / "audio"
        if audio_dir.is_dir():
            srt_files = list(audio_dir.glob("*.srt"))
    srt_path = srt_files[0] if srt_files else None

    if not body.selections:
        raise HTTPException(
            status_code=400,
            detail="No selections provided",
        )

    try:
        suggestions = analyze_folder(project_dir)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze project: {e}",
        )

    if not suggestions:
        raise HTTPException(
            status_code=400,
            detail="No suggestions available for rendering",
        )

    shorts_dir = project_dir / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)

    results: list[RenderResult] = []
    custom_srt_files: list[Path] = []
    manual_by_idx = {c.index: c for c in body.manual_clips}
    for idx in body.selections:
        # Check if it's a manual clip first
        if idx in manual_by_idx:
            mc = manual_by_idx[idx]

            # Build custom SRT from word timestamps if word indices provided
            custom_srt = None
            if mc.start_word_idx is not None and mc.end_word_idx is not None:
                custom_srt = _build_srt_from_words(project_dir, mc.start_word_idx, mc.end_word_idx)
                if custom_srt:
                    custom_srt_files.append(custom_srt)

            s = ClipSuggestion(
                start_sec=mc.start_sec,
                end_sec=mc.end_sec,
                score=10.0,
                reason=mc.reason,
                text_preview=mc.text_preview,
            )
            # Override srt for this clip
            if custom_srt:
                srt_path = custom_srt
        elif idx >= 0 and idx < len(suggestions):
            s = suggestions[idx]
        else:
            results.append(
                RenderResult(
                    index=idx,
                    filename="",
                    success=False,
                    error=f"Invalid index {idx}, max is {len(suggestions) - 1}",
                )
            )
            continue
        out_name = f"{project_id}_short_{idx:02d}.mp4"
        out_path = shorts_dir / out_name

        job = RenderJob(
            suggestion=s,
            video_path=video_path,
            srt_path=srt_path if body.with_subtitles else None,
            output_path=out_path,
            font_size=body.font_size,
        )

        try:
            render_job(job)
            results.append(
                RenderResult(index=idx, filename=out_name, success=True)
            )
        except Exception as e:
            results.append(
                RenderResult(
                    index=idx,
                    filename="",
                    success=False,
                    error=str(e),
                )
            )

    # Clean up custom SRT files created for manual clips
    for f in custom_srt_files:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass

    return RenderResponse(results=results)


@router.get("/downloads")
async def list_downloads(project_id: str) -> DownloadsResponse:
    """List available rendered short files."""
    project_dir = await _resolve_project_dir(project_id)
    shorts_dir = project_dir / "shorts"

    if not shorts_dir.exists():
        return DownloadsResponse(files=[])

    files = []
    for f in sorted(shorts_dir.glob("*.mp4")):
        files.append(
            DownloadItem(filename=f.name, size_bytes=f.stat().st_size)
        )

    return DownloadsResponse(files=files)


@router.get("/file/{filename}")
async def download_file(project_id: str, filename: str):
    """Download a rendered short file."""
    project_dir = await _resolve_project_dir(project_id)
    file_path = project_dir / "shorts" / filename

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {filename}",
        )

    if file_path.suffix.lower() not in (".mp4", ".mov", ".webm"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type",
        )

    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=filename,
    )
