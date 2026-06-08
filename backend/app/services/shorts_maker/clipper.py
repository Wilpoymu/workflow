from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.services.shorts_maker.types import RenderJob


def _run_ffmpeg(args: list[str], description: str = "") -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        label = f" ({description})" if description else ""
        raise RuntimeError(
            f"ffmpeg failed{label}:\n{' '.join(cmd)}\n{result.stderr}"
        )


def clip_video(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
) -> None:
    duration = end_sec - start_sec
    _run_ffmpeg(
        [
            "-ss", str(start_sec),
            "-i", str(input_path),
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ],
        f"clip {start_sec:.1f}-{end_sec:.1f}",
    )


def convert_to_vertical(
    input_path: Path,
    output_path: Path,
    target_width: int = 1080,
    target_height: int = 1920,
) -> None:
    x_center = "iw/2"
    crop_width = f"ih*{target_width}/{target_height}"
    crop_filter = (
        f"crop={crop_width}:ih:{x_center}-({crop_width})/2:0,"
        f"scale={target_width}:{target_height}:flags=lanczos"
    )

    _run_ffmpeg(
        [
            "-i", str(input_path),
            "-vf", crop_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            str(output_path),
        ],
        "convert to vertical",
    )


def clip_and_convert(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
    target_width: int = 1080,
    target_height: int = 1920,
) -> None:
    duration = end_sec - start_sec
    x_center = "iw/2"
    crop_width = f"ih*{target_width}/{target_height}"
    crop_filter = (
        f"crop={crop_width}:ih:{x_center}-({crop_width})/2:0,"
        f"scale={target_width}:{target_height}:flags=lanczos"
    )

    _run_ffmpeg(
        [
            "-ss", str(start_sec),
            "-i", str(input_path),
            "-t", str(duration),
            "-vf", crop_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ],
        f"clip+vertical {start_sec:.1f}-{end_sec:.1f}",
    )


def get_video_info(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    import json
    return json.loads(result.stdout)


def render_job(job: RenderJob) -> Path:
    job.output_path.parent.mkdir(parents=True, exist_ok=True)

    if job.srt_path and job.srt_path.exists():
        return _render_with_subtitles(job)

    return _render_without_subtitles(job)


def _render_without_subtitles(job: RenderJob) -> Path:
    duration = job.suggestion.end_sec - job.suggestion.start_sec
    x_center = "iw/2"
    crop_width = f"ih*{job.width}/{job.height}"
    crop_filter = (
        f"crop={crop_width}:ih:{x_center}-({crop_width})/2:0,"
        f"scale={job.width}:{job.height}:flags=lanczos"
    )

    _run_ffmpeg(
        [
            "-ss", str(job.suggestion.start_sec),
            "-i", str(job.video_path),
            "-t", str(duration),
            "-vf", crop_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            str(job.output_path),
        ],
        "render without subtitles",
    )
    return job.output_path


def _render_with_subtitles(job: RenderJob) -> Path:
    from app.services.shorts_maker.subtitler import create_subtitle_ass, extract_srt_segment

    temp_srt = job.output_path.with_suffix(".segment.srt")
    extract_srt_segment(
        job.srt_path,  # type: ignore[arg-type]
        temp_srt,
        job.suggestion.start_sec,
        job.suggestion.end_sec,
    )

    ass_path = job.output_path.with_suffix(".ass")
    create_subtitle_ass(
        temp_srt,
        ass_path,
        video_width=job.width,
        video_height=job.height,
    )

    duration = job.suggestion.end_sec - job.suggestion.start_sec
    x_center = "iw/2"
    crop_width = f"ih*{job.width}/{job.height}"

    escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")

    vf = (
        f"crop={crop_width}:ih:{x_center}-({crop_width})/2:0,"
        f"scale={job.width}:{job.height}:flags=lanczos,"
        f"ass='{escaped_ass}'"
    )

    _run_ffmpeg(
        [
            "-ss", str(job.suggestion.start_sec),
            "-i", str(job.video_path),
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            str(job.output_path),
        ],
        "render with subtitles",
    )

    temp_srt.unlink(missing_ok=True)
    ass_path.unlink(missing_ok=True)

    return job.output_path
