"""Auto-migration: fragments (prompts-*.json) → timeline.json.

Scans a project directory, loads fragments from all prompts-*.json files,
maps each fragment to a video track clip with sequential timing, and
optionally adds audio and subtitle tracks from existing media files.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

__all__ = ["auto_migrate"]

# ── Constants ────────────────────────────────────────────────────────────────

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
"""Image file extensions to search for, in priority order."""

AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a")
"""Audio file extensions to search for in the audio/ directory."""

DEFAULT_CLIP_DURATION = 5.0
"""Fallback duration per clip when the fragment has no timestamps."""


# ── Public API ───────────────────────────────────────────────────────────────

def auto_migrate(project_dir: str) -> dict | None:
    """Auto-generate a *timeline.json* dict from project fragments and media.

    The function is **idempotent** — it reads the project directory, never
    writes anything, and returns a plain dict that the caller can save as
    ``timeline.json``.

    Steps
    -----
    1.  Find **all** ``prompts-*.json`` files in *project_dir*.
    2.  Load fragments from every file, deduplicating by ``fragment_id``.
    3.  Check that ``imagenes/`` exists.
    4.  For each fragment, build a video clip:
        - ``id``: ``"clip_{fragment_id}"``
        - ``source_path``: ``"imagenes/{fragment_id}.png"`` (or ``.jpg``,
          ``.jpeg``, ``.webp``); falls back to ``escena_``-prefixed names
          for backward compatibility with the legacy pipeline.
        - ``start_time``: cumulative (clips are sequential, no gaps).
        - ``duration``: ``end_time - start_time`` when both are present on
          the fragment; otherwise defaults to **5.0 seconds**.
        - ``movement``: ``"zoom_in"`` (randomization deferred to Phase 2).
    5.  Add an **audio track** if ``audio/`` contains an ``.mp3`` / ``.wav`` /
        ``.m4a`` file.
    6.  Add a **subtitle track** (locked, empty clips array) only when
        ``audio/script.srt`` exists.
    7.  Return the complete timeline dict.

    Parameters
    ----------
    project_dir : str
        Absolute or relative path to the project folder.

    Returns
    -------
    dict | None
        A timeline dict matching the schema below, or ``None`` when migration
        is not possible (no fragments found, missing ``imagenes/``, or no
        clips could be built).

    Timeline JSON schema
    --------------------
    .. code-block:: json

        {
          "version": 1,
          "canvas": {"width": 1920, "height": 1080, "fps": 30},
          "duration": 30.0,
          "tracks": [
            {
              "id": "video_0",
              "type": "video",
              "name": "Video",
              "muted": false,
              "locked": false,
              "clips": [...]
            },
            {
              "id": "audio_0",
              "type": "audio",
              "name": "Narration",
              "muted": false,
              "locked": false,
              "clips": [...]
            },
            {
              "id": "subtitle_0",
              "type": "subtitle",
              "name": "Subtitles",
              "muted": false,
              "locked": true,
              "clips": []
            }
          ]
        }

    Edge cases
    ----------
    - No ``prompts-*.json`` files → returns ``None``
    - ``imagenes/`` directory missing → returns ``None``
    - Empty fragments list → returns ``None``
    - Fragment has both ``start_time`` and ``end_time`` → uses ``end - start``
    - Fragment missing timestamps → defaults to **5 seconds**
    - Fragment has **only one** of ``start_time`` / ``end_time`` → treated as
      "no timestamps", defaults to **5 seconds**
    - Image ``{fragment_id}.png`` doesn't exist → tries ``.jpg``, ``.jpeg``,
      ``.webp``, then ``escena_{fragment_id:03d}.{ext}`` (legacy naming), and
      **skips** the fragment if none found
    - No audio file found → audio track is omitted entirely
    - No ``audio/script.srt`` → subtitle track is **omitted** entirely
    """
    project_path = Path(project_dir).resolve()

    # ── 1. Load fragments from ALL prompts-*.json files ──────────────────
    fragments = _load_fragments(project_path)
    if not fragments:
        return None

    # ── 2. Ensure imagenes/ exists ───────────────────────────────────────
    img_dir = project_path / "imagenes"
    if not img_dir.is_dir():
        return None

    # ── 3. Build video clips ────────────────────────────────────────────
    clips: list[dict] = []
    cursor = 0.0  # cumulative start_time

    for f in fragments:
        fid: int = f["fragment_id"]

        # Duration — use timestamps only when BOTH are present
        duration = _resolve_duration(f)

        # Resolve image file (new naming → legacy escena_ fallback)
        source_path = _resolve_image(img_dir, fid)
        if source_path is None:
            continue  # skip fragment — image not found on disk

        clip: dict = {
            "id": f"clip_{fid}",
            "source_type": "image",
            "source_path": source_path,
            "start_time": cursor,
            "duration": duration,
            "trim_in": 0.0,
            "trim_out": duration,
            "movement": "zoom_in",
            "intensity": 0.05,
        }
        clips.append(clip)
        cursor += duration

    if not clips:
        return None

    total_duration = cursor

    # ── 4. Build tracks ─────────────────────────────────────────────────
    tracks: list[dict] = []

    # Video track (always present)
    tracks.append(_video_track(clips))

    # Audio track (optional)
    audio_path = _find_audio_file(project_path)
    if audio_path is not None:
        tracks.append(_audio_track(audio_path, total_duration))

    # Subtitle track (only if SRT file exists — locked, empty clips)
    if _has_subtitle_file(project_path):
        tracks.append(_subtitle_track())

    # ── 5. Assemble timeline ────────────────────────────────────────────
    return {
        "version": 1,
        "canvas": {"width": 1920, "height": 1080, "fps": 30},
        "duration": total_duration,
        "tracks": tracks,
    }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _load_fragments(project_path: Path) -> list[dict]:
    """Load and deduplicate fragments from all ``prompts-*.json`` files."""
    prompts_files = sorted(project_path.glob("prompts-*.json"))
    if not prompts_files:
        return []

    seen: set[int] = set()
    all_fragments: list[dict] = []

    for pf in prompts_files:
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, list):
            continue

        for item in data:
            fid = item.get("fragment_id")
            if fid is None or not isinstance(fid, int):
                continue
            if fid in seen:
                continue
            seen.add(fid)
            all_fragments.append(item)

    # Sort by fragment_id to ensure deterministic clip order
    all_fragments.sort(key=lambda x: x["fragment_id"])
    return all_fragments


def _resolve_duration(fragment: dict) -> float:
    """Return clip duration from fragment timestamps, or default."""
    start = fragment.get("start_time")
    end = fragment.get("end_time")
    if start is not None and end is not None:
        dur = end - start
        # Guard against zero / negative / NaN / Inf durations
        if dur > 0 and not math.isnan(dur) and not math.isinf(dur):
            return dur
    return DEFAULT_CLIP_DURATION


def _resolve_image(img_dir: Path, fragment_id: int) -> str | None:
    """Find an image file for *fragment_id* in *img_dir*.

    Tries (in order):
    1. ``{fragment_id}.{ext}`` for each extension in IMAGE_EXTENSIONS
    2. ``escena_{fragment_id:03d}.{ext}`` (legacy pipeline naming)

    Returns the **relative path** suitable for ``source_path`` in the
    timeline JSON, or ``None`` when no matching image exists.
    """
    # New naming: {fragment_id}.png / .jpg / .jpeg / .webp
    for ext in IMAGE_EXTENSIONS:
        candidate = img_dir / f"{fragment_id}{ext}"
        if candidate.is_file():
            return f"imagenes/{fragment_id}{ext}"

    # Legacy naming: escena_{fragment_id:03d}.png / .jpg / etc.
    for ext in IMAGE_EXTENSIONS:
        candidate = img_dir / f"escena_{fragment_id:03d}{ext}"
        if candidate.is_file():
            return f"imagenes/escena_{fragment_id:03d}{ext}"

    return None


def _find_audio_file(project_path: Path) -> Path | None:
    """Return the first audio file found in ``audio/``, or ``None``."""
    audio_dir = project_path / "audio"
    if not audio_dir.is_dir():
        return None
    for ext in AUDIO_EXTENSIONS:
        matches = sorted(audio_dir.glob(f"*{ext}"))
        if matches:
            return matches[0]
    return None


def _has_subtitle_file(project_path: Path) -> bool:
    """Return ``True`` when ``audio/script.srt`` exists."""
    return (project_path / "audio" / "script.srt").is_file()


# ── Track builders ───────────────────────────────────────────────────────────

def _video_track(clips: list[dict]) -> dict:
    return {
        "id": "video_0",
        "type": "video",
        "name": "Video",
        "muted": False,
        "locked": False,
        "clips": clips,
    }


def _audio_track(audio_path: Path, duration: float) -> dict:
    safe_duration = duration if isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0 else DEFAULT_CLIP_DURATION
    return {
        "id": "audio_0",
        "type": "audio",
        "name": "Narration",
        "muted": False,
        "locked": False,
        "clips": [
            {
                "id": "audio_clip_0",
                "source_type": "audio",
                "source_path": f"audio/{audio_path.name}",
                "start_time": 0.0,
                "duration": safe_duration,
                "volume": 1.0,
            }
        ],
    }


def _subtitle_track() -> dict:
    return {
        "id": "subtitle_0",
        "type": "subtitle",
        "name": "Subtitles",
        "muted": False,
        "locked": True,
        "clips": [],
    }
