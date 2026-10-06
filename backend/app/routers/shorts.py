import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import project_service
from app.services.shorts_maker.analyzer import analyze_folder, find_video_in_folder
from app.services.shorts_maker.ai_analyzer import generate_ai_segments, analyze_segments_batch
from app.services.shorts_maker.clipper import render_job
from app.services.shorts_maker.srt_parser import entries_in_range, parse_srt
from app.services.shorts_maker.types import ClipSuggestion, RenderJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/shorts", tags=["shorts"])

ANALYSIS_CACHE_FILE = "shorts/analysis.json"


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


class SuggestionItem(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    duration: float
    score: float
    reason: str
    text_preview: str
    ai_hook: str | None = None
    ai_category: str | None = None
    ai_viral_potential: str | None = None


class AnalyzeResponse(BaseModel):
    suggestions: list[SuggestionItem]
    cached: bool = False
    generated_at: str | None = None
    mode: str = "ai"


class CachedAnalysis(BaseModel):
    mode: str
    generated_at: str
    suggestions: list[SuggestionItem]


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
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return Path(project.base_dir)


def _cache_path(project_dir: Path) -> Path:
    return project_dir / ANALYSIS_CACHE_FILE


def _load_cache(project_dir: Path) -> dict | None:
    path = _cache_path(project_dir)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_cache(project_dir: Path, data: dict) -> None:
    path = _cache_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_srt_from_words(project_dir: Path, start_idx: int, end_idx: int) -> Path | None:
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


def _suggestions_to_dicts(suggestions: list[SuggestionItem]) -> list[dict]:
    return [s.model_dump() for s in suggestions]


def _dicts_to_suggestions(items: list[dict]) -> list[SuggestionItem]:
    return [SuggestionItem(**item) for item in items]


@router.get("/analysis")
async def get_cached_analysis(project_id: str) -> AnalyzeResponse:
    """Return cached analysis if available."""
    project_dir = await _resolve_project_dir(project_id)
    cached = _load_cache(project_dir)
    if not cached:
        return AnalyzeResponse(suggestions=[], cached=False, mode="ai")
    return AnalyzeResponse(
        suggestions=_dicts_to_suggestions(cached.get("suggestions", [])),
        cached=True,
        generated_at=cached.get("generated_at"),
        mode=cached.get("mode", "ai"),
    )


@router.post("/analyze")
async def analyze_project(
    project_id: str,
    mode: str = Query("ai", description="Analysis mode: 'ai' (AI generates segments), 'rules' (rule-based), 'combined' (both)"),
    refresh: bool = Query(False, description="Force re-analysis, ignoring cache"),
) -> AnalyzeResponse:
    """Analyze project folder and suggest best moments for shorts."""
    project_dir = await _resolve_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project directory not found: {project_dir}")

    if mode not in ("ai", "rules", "combined"):
        mode = "ai"

    # Check cache first (unless refresh)
    if not refresh:
        cached = _load_cache(project_dir)
        if cached and cached.get("mode") == mode:
            logger.info("Using cached analysis for project %s (mode=%s)", project_id, mode)
            return AnalyzeResponse(
                suggestions=_dicts_to_suggestions(cached.get("suggestions", [])),
                cached=True,
                generated_at=cached.get("generated_at"),
                mode=mode,
            )

    logger.info("Running fresh analysis for project %s (mode=%s)", project_id, mode)

    # Find SRT file
    srt_files = list(project_dir.glob("*.srt"))
    if not srt_files:
        audio_dir = project_dir / "audio"
        if audio_dir.is_dir():
            srt_files = list(audio_dir.glob("*.srt"))
    script_srt = [f for f in srt_files if f.name.lower() == "script.srt"]
    srt_path = script_srt[0] if script_srt else (srt_files[0] if srt_files else None)

    if not srt_path:
        raise HTTPException(status_code=400, detail="No SRT file found in project")

    entries = parse_srt(srt_path)
    if not entries:
        raise HTTPException(status_code=400, detail="Could not parse SRT file")

    # --- AI mode: generate segments from full transcript ---
    if mode == "ai":
        try:
            ai_segments = await generate_ai_segments(entries, top_n=15)
        except Exception as e:
            logger.error("AI segment generation failed: %s", e)
            raise HTTPException(
                status_code=500,
                detail=f"AI analysis failed: {e}. Make sure Gemini Web cookies are configured.",
            )

        if not ai_segments:
            return AnalyzeResponse(suggestions=[], mode=mode)

        results = []
        for i, seg in enumerate(ai_segments):
            reason = f"ai:{seg.get('ai_category', 'General')}"
            ai_reason = seg.get("ai_reason", "")
            if ai_reason:
                reason += f"|{ai_reason}"

            results.append(
                SuggestionItem(
                    index=i,
                    start_sec=seg["start_sec"],
                    end_sec=seg["end_sec"],
                    duration=seg["end_sec"] - seg["start_sec"],
                    score=round(seg.get("ai_score", 5.0), 2),
                    reason=reason,
                    text_preview=seg.get("text", ""),
                    ai_hook=seg.get("ai_hook", "medio"),
                    ai_category=seg.get("ai_category", "General"),
                    ai_viral_potential=seg.get("ai_viral_potential", "medio"),
                )
            )

        results.sort(key=lambda x: x.score, reverse=True)
        for i, r in enumerate(results):
            r.index = i

        # Persist to cache
        now = datetime.now(timezone.utc).isoformat()
        _save_cache(project_dir, {
            "mode": mode,
            "generated_at": now,
            "suggestions": _suggestions_to_dicts(results),
        })

        return AnalyzeResponse(suggestions=results, mode=mode, generated_at=now)

    # --- Rules and Combined modes: rule-based segmentation first ---
    try:
        suggestions = analyze_folder(project_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze project: {e}")

    if not suggestions:
        return AnalyzeResponse(suggestions=[], mode=mode)

    if mode == "rules":
        results = [
            SuggestionItem(
                index=i,
                start_sec=s.start_sec,
                end_sec=s.end_sec,
                duration=s.duration,
                score=s.score,
                reason=s.reason,
                text_preview=s.text_preview,
            )
            for i, s in enumerate(suggestions)
        ]
        now = datetime.now(timezone.utc).isoformat()
        _save_cache(project_dir, {
            "mode": mode,
            "generated_at": now,
            "suggestions": _suggestions_to_dicts(results),
        })
        return AnalyzeResponse(suggestions=results, mode=mode, generated_at=now)

    # Combined mode: score rule-based segments with AI
    try:
        segments_for_ai = [
            {"start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text_preview}
            for s in suggestions
        ]
        ai_results = await analyze_segments_batch(segments_for_ai)
    except Exception as e:
        logger.warning("AI analysis failed for combined mode, falling back to rules: %s", e)
        results = [
            SuggestionItem(
                index=i,
                start_sec=s.start_sec,
                end_sec=s.end_sec,
                duration=s.duration,
                score=s.score,
                reason=s.reason,
                text_preview=s.text_preview,
            )
            for i, s in enumerate(suggestions)
        ]
        now = datetime.now(timezone.utc).isoformat()
        _save_cache(project_dir, {
            "mode": mode,
            "generated_at": now,
            "suggestions": _suggestions_to_dicts(results),
        })
        return AnalyzeResponse(suggestions=results, mode=mode, generated_at=now)

    results = []
    for i, (orig, ai) in enumerate(zip(suggestions, ai_results)):
        final_score = (orig.score + ai["ai_score"]) / 2
        ai_cat = ai.get("ai_category", "General")
        ai_reason = ai.get("ai_reason", "")
        reason = f"ai:{ai_cat}"
        if ai_reason:
            reason += f"|{ai_reason}"

        results.append(
            SuggestionItem(
                index=i,
                start_sec=orig.start_sec,
                end_sec=orig.end_sec,
                duration=orig.duration,
                score=round(final_score, 2),
                reason=reason,
                text_preview=orig.text_preview,
                ai_hook=ai.get("ai_hook", "medio"),
                ai_category=ai_cat,
                ai_viral_potential=ai.get("ai_viral_potential", "medio"),
            )
        )

    results.sort(key=lambda x: x.score, reverse=True)
    for i, r in enumerate(results):
        r.index = i

    now = datetime.now(timezone.utc).isoformat()
    _save_cache(project_dir, {
        "mode": mode,
        "generated_at": now,
        "suggestions": _suggestions_to_dicts(results),
    })

    return AnalyzeResponse(suggestions=results, mode=mode, generated_at=now)


@router.post("/render")
async def render_shorts(project_id: str, body: RenderRequest) -> RenderResponse:
    """Render selected shorts for the project."""
    project_dir = await _resolve_project_dir(project_id)

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project directory not found: {project_dir}")

    video_path = find_video_in_folder(project_dir)
    if not video_path:
        raise HTTPException(status_code=400, detail="No video found in project directory")

    srt_files = list(project_dir.glob("*.srt"))
    if not srt_files:
        audio_dir = project_dir / "audio"
        if audio_dir.is_dir():
            srt_files = list(audio_dir.glob("*.srt"))
    srt_path = srt_files[0] if srt_files else None

    if not body.selections:
        raise HTTPException(status_code=400, detail="No selections provided")

    # Try cached analysis first, then fall back to fresh analysis
    cached = _load_cache(project_dir)
    if cached:
        suggestions = _dicts_to_suggestions(cached.get("suggestions", []))
    else:
        try:
            suggestions = analyze_folder(project_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to analyze project: {e}")

    if not suggestions and not body.manual_clips:
        raise HTTPException(status_code=400, detail="No suggestions available for rendering")

    shorts_dir = project_dir / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)

    for f in shorts_dir.iterdir():
        if f.suffix.lower() in (".srt", ".ass") and f.is_file():
            try:
                f.unlink()
            except OSError:
                pass

    results: list[RenderResult] = []
    custom_srt_files: list[Path] = []
    manual_by_idx = {c.index: c for c in body.manual_clips}
    for idx in body.selections:
        if idx in manual_by_idx:
            mc = manual_by_idx[idx]

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
            if custom_srt:
                srt_path = custom_srt
        elif idx >= 0 and idx < len(suggestions):
            s = suggestions[idx]
        else:
            results.append(
                RenderResult(index=idx, filename="", success=False, error=f"Invalid index {idx}, max is {len(suggestions) - 1}")
            )
            continue
        out_name = f"{project_id}_short_{idx:02d}.mp4"
        out_path = shorts_dir / out_name
        if out_path.exists():
            ver = 2
            while True:
                versioned = shorts_dir / f"{project_id}_short_{idx:02d}_v{ver}.mp4"
                if not versioned.exists():
                    out_path = versioned
                    out_name = versioned.name
                    break
                ver += 1

        job = RenderJob(
            suggestion=s,
            video_path=video_path,
            srt_path=srt_path if body.with_subtitles else None,
            output_path=out_path,
            font_size=body.font_size,
        )

        try:
            render_job(job)
            results.append(RenderResult(index=idx, filename=out_name, success=True))
        except Exception as e:
            results.append(RenderResult(index=idx, filename="", success=False, error=str(e)))

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
        files.append(DownloadItem(filename=f.name, size_bytes=f.stat().st_size))

    return DownloadsResponse(files=files)


@router.get("/file/{filename}")
async def download_file(project_id: str, filename: str):
    """Download a rendered short file."""
    project_dir = await _resolve_project_dir(project_id)
    file_path = project_dir / "shorts" / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    if file_path.suffix.lower() not in (".mp4", ".mov", ".webm"):
        raise HTTPException(status_code=400, detail="Invalid file type")

    return FileResponse(path=str(file_path), media_type="video/mp4", filename=filename)
