"""
clip_renderer.py — Reusable Ken Burns clip rendering primitives.

Extracted from kenburns.py for modular use in the CapCut-style timeline editor.
Provides low-level building blocks: image clip rendering with Ken Burns
effects, clip concatenation, zoompan expression generation, and ffmpeg
utilities.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


# ---------------------------------------------------------------------------
# Low-level ffmpeg helpers
# ---------------------------------------------------------------------------


def _run_ffmpeg(cmd: list[str]) -> tuple[int, str, str]:
    """Run ffmpeg synchronously (call in thread pool for async callers).

    Returns (returncode, stdout_str, stderr_str).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_SUBPROCESS_FLAGS,
    )
    stdout, stderr = proc.communicate()
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def _detect_hw_encoder() -> tuple[str, list[str]]:
    """Detect the best available hardware encoder.

    Tries NVIDIA NVENC → AMD AMF → software libx264.
    Returns (encoder_name, hw_params_list).
    """
    try:
        nv = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if nv.returncode == 0:
            return "h264_nvenc", [
                "-c:v", "h264_nvenc",
                "-preset", "p1",
                "-rc", "vbr",
            ]
    except FileNotFoundError:
        pass

    try:
        enc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if "h264_amf" in enc.stdout:
            return "h264_amf", [
                "-c:v", "h264_amf",
                "-preset", "speed",
                "-quality", "balanced",
            ]
    except FileNotFoundError:
        pass

    return "libx264", ["-c:v", "libx264", "-preset", "veryfast"]


# ---------------------------------------------------------------------------
# Image / geometry helpers
# ---------------------------------------------------------------------------


def _scale_cover(img_w: int, img_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    """Calculate the dimensions to scale *img_w × img_h* so it *covers*
    *target_w × target_h* while preserving aspect ratio (CSS ``object-fit:
    cover`` semantics).

    Returns (scaled_w, scaled_h) — at least one axis equals the target,
    the other is >= target.
    """
    img_ratio = img_w / img_h
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        # image is wider → height constrains
        new_h = target_h
        new_w = int(new_h * img_ratio)
    else:
        # image is taller (or equal) → width constrains
        new_w = target_w
        new_h = int(new_w / img_ratio)

    return new_w, new_h


# ---------------------------------------------------------------------------
# Zoompan expression generator
# ---------------------------------------------------------------------------


def _zoompan_expr(
    movement: str,
    frames: int,
    out_w: int,
    out_h: int,
    canvas_w: int,
    canvas_h: int,
    fps: int,
) -> str:
    """Build an ffmpeg ``zoompan`` filter expression for one Ken Burns clip.

    Parameters
    ----------
    movement : str
        One of ``zoom_in``, ``zoom_out``, ``pan_right``, ``pan_left``,
        ``pan_up``, ``pan_down``.
    frames : int
        Number of frames the clip should last.
    out_w, out_h : int
        Output (render) dimensions — the final size of the zoompan output.
    canvas_w, canvas_h : int
        Virtual canvas size (output + margins for movement).
    fps : int
        Framerate encoded into the zoompan expression.

    Returns
    -------
    str
        A ``zoompan=...`` filter string ready to pass to ``-vf``.
    """
    zf = canvas_w / out_w
    mx = canvas_w - out_w
    my = canvas_h - out_h
    cx = mx / 2
    cy = my / 2

    d = frames - 1 if frames > 1 else 1
    T = f"on/{d}"
    eased = f"({T})*({T})*(3-2*({T}))"

    if movement == "zoom_in":
        z = f"1+({zf}-1)*({eased})"
        x = f"(in_w - in_w/(1+({zf}-1)*({eased})))/2"
        y = f"(in_h - in_h/(1+({zf}-1)*({eased})))/2"
    elif movement == "zoom_out":
        z = f"{zf}-({zf}-1)*({eased})"
        x = f"(in_w - in_w/({zf}-({zf}-1)*({eased})))/2"
        y = f"(in_h - in_h/({zf}-({zf}-1)*({eased})))/2"
    elif movement == "pan_right":
        z = f"{zf}"
        x = f"{mx} * ({eased})"
        y = f"{cy}"
    elif movement == "pan_left":
        z = f"{zf}"
        x = f"{mx} * (1-({eased}))"
        y = f"{cy}"
    elif movement == "pan_up":
        z = f"{zf}"
        x = f"{cx}"
        y = f"{my} * ({eased})"
    else:  # pan_down
        z = f"{zf}"
        x = f"{cx}"
        y = f"{my} * (1-({eased}))"

    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={out_w}x{out_h}:fps={fps}"


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


def render_image_clip(
    img_path: str,
    movement: str,
    duration_sec: float,
    fps: int,
    canvas_w: int,
    canvas_h: int,
    output_path: str,
    intensity: float = 0.05,
) -> bool:
    """Render a single still image as a video clip with a Ken Burns movement.

    Internally renders at 2× the target resolution for oversampling quality,
    matching the original ``kenburns.py`` behaviour so concatenation can
    downscale to the final size.

    Parameters
    ----------
    img_path : str
        Path to the source image.
    movement : str
        One of the six Ken Burns movements.
    duration_sec : float
        Desired clip duration in seconds.
    fps : int
        Output framerate.
    canvas_w, canvas_h : int
        **Final** output dimensions (before the internal 2× upscale).
    output_path : str
        Where to write the rendered ``.mp4``.
    intensity : float, optional
        Movement intensity factor (default 0.05, clamped 0.01–0.15
        by the caller if desired).

    Returns
    -------
    bool
        ``True`` if ffmpeg succeeded, ``False`` otherwise.
    """
    from PIL import Image

    img = Image.open(img_path)
    img_w, img_h = img.size

    # Render at 2× for quality (matching original kenburns.py)
    render_w = canvas_w * 2
    render_h = canvas_h * 2
    margin_x = int(render_w * intensity)
    margin_y = int(render_h * intensity)
    render_canvas_w = render_w + margin_x * 2
    render_canvas_h = render_h + margin_y * 2

    # Scale image to cover the render canvas
    sw, sh = _scale_cover(img_w, img_h, render_canvas_w, render_canvas_h)

    # Number of frames
    num_frames = max(1, round(duration_sec * fps))

    # Build zoompan expression
    zp_expr = _zoompan_expr(
        movement, num_frames, render_w, render_h,
        render_canvas_w, render_canvas_h, fps,
    )

    # Select clip encoder (matches the original logic in kenburns.py)
    hw_encoder, _ = _detect_hw_encoder()
    if hw_encoder == "h264_nvenc":
        clip_encoder = ["-c:v", "h264_nvenc", "-preset", "p1", "-qp", "18"]
    elif hw_encoder == "h264_amf":
        clip_encoder = ["-c:v", "h264_amf", "-preset", "speed", "-quality", "balanced"]
    else:
        clip_encoder = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"]

    # Assemble ffmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", img_path,
        "-vf", f"scale={sw}:{sh},setsar=1,{zp_expr}",
    ]
    cmd.extend(clip_encoder)
    cmd.extend(["-pix_fmt", "yuv420p", "-an", output_path])

    ret, _, _ = _run_ffmpeg(cmd)
    return ret == 0


def concat_clips(
    clip_paths: list[str],
    output_path: str,
    audio_path: Optional[str] = None,
    total_duration: Optional[float] = None,
    hw_params: Optional[list[str]] = None,
    output_w: Optional[int] = None,
    output_h: Optional[int] = None,
) -> bool:
    """Concatenate multiple video clips into a single file, optionally mixing
    an audio track.

    Writes a temporary concat demuxer file next to *output_path*.

    Parameters
    ----------
    clip_paths : list[str]
        Paths to the video clips to concatenate (must all share the same
        codec parameters).
    output_path : str
        Destination path for the final video.
    audio_path : str or None, optional
        If provided, the audio track is mixed into the output.
    total_duration : float or None, optional
        When *audio_path* is set, trim the output to this duration.
    hw_params : list[str] or None, optional
        Extra ffmpeg parameters (typically encoder flags from
        :func:`_detect_hw_encoder`).
    output_w, output_h : int or None, optional
        If both provided, the concatenated video is scaled to these
        dimensions (via Lanczos).  Required to match the original
        ``kenburns.py`` behaviour of rendering at 2× and downscaling.

    Returns
    -------
    bool
        ``True`` on success, ``False`` if ffmpeg returned an error.
    """
    # Write concat demuxer file
    concat_dir = Path(output_path).parent
    concat_dir.mkdir(parents=True, exist_ok=True)

    concat_list = concat_dir / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for clip in clip_paths:
            abs_path = str(Path(clip).resolve()).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    # Build ffmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
    ]

    if audio_path:
        cmd.extend(["-i", audio_path])

    # Scale to final output dimensions when provided (2× → 1× downscale)
    if output_w is not None and output_h is not None:
        cmd.extend(["-vf", f"scale={output_w}:{output_h}:flags=lanczos"])

    if hw_params:
        cmd.extend(hw_params)

    cmd.extend([
        "-b:v", "4M",
        "-maxrate", "5M",
        "-bufsize", "5M",
        "-profile:v", "high",
        "-level", "4.0",
    ])

    if audio_path:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    if total_duration is not None:
        cmd.extend(["-t", str(total_duration)])

    cmd.extend(["-pix_fmt", "yuv420p", output_path])

    ret, _, _ = _run_ffmpeg(cmd)
    return ret == 0


def xconcat_clips(
    clip_paths: list[str],
    clip_durations: list[float],
    output_path: str,
    transitions: list[dict] | None = None,
    audio_path: str | None = None,
    hw_params: list[str] | None = None,
    output_w: int = 1920,
    output_h: int = 1080,
    fps: int = 30,
) -> bool:
    """Concatenate clips with xfade transitions using filter_complex.

    Each pre-rendered clip is expected to be a video-only MP4 (no audio
    stream — which is the case for clips produced by :func:`render_image_clip`).
    Audio is handled separately via *audio_path* (mixed as an additional
    input, not acrossfaded between clips).

    Parameters
    ----------
    clip_paths : list[str]
        Ordered list of paths to pre-rendered clip MP4s.
    clip_durations : list[float]
        Duration in seconds for each clip in *clip_paths*.  Must have the
        same length as *clip_paths*.
    output_path : str
        Path for the final output MP4.
    transitions : list[dict] | None, optional
        Transition descriptors between consecutive clips.
        ``transitions[i]`` applies between ``clip_paths[i]`` and
        ``clip_paths[i+1]``.  Each entry::

            {"type": "fade", "duration": 1.0}

        When ``None`` or empty, falls back to :func:`concat_clips` (simple
        concat demuxer — no filter_complex overhead).
    audio_path : str | None, optional
        If provided, this audio file is mixed into the output (mapped
        separately, not passed through ``acrossfade``).
    hw_params : list[str] | None, optional
        Extra ffmpeg parameters (typically encoder flags from
        :func:`_detect_hw_encoder`).
    output_w, output_h : int
        Output resolution (default 1920×1080).
    fps : int
        Framerate (default 30).  Used for ``setpts`` consistency.

    Returns
    -------
    bool
        ``True`` on success, ``False`` if ffmpeg returned an error.
    """
    # ── Fallback: no transitions → simple concat ──────────────────────
    if not transitions:
        logger.info("No transitions — delegating to concat_clips")
        return concat_clips(
            clip_paths=clip_paths,
            output_path=output_path,
            audio_path=audio_path,
            hw_params=hw_params,
            output_w=output_w,
            output_h=output_h,
        )

    n = len(clip_paths)
    if n < 2:
        logger.info("Single clip — copying directly")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(clip_paths[0], output_path)
        return True

    if len(transitions) != n - 1:
        logger.warning(
            "Expected %d transitions for %d clips, got %d — falling back to "
            "simple concat.",
            n - 1, n, len(transitions),
        )
        return concat_clips(
            clip_paths=clip_paths,
            output_path=output_path,
            audio_path=audio_path,
            hw_params=hw_params,
            output_w=output_w,
            output_h=output_h,
        )

    # ── Build filter_complex graph ────────────────────────────────────
    #
    # For N clips with N-1 transitions:
    #
    #   [0:v]scale=W:H:flags=lanczos,setpts=PTS[v0];
    #   [1:v]scale=W:H:flags=lanczos,setpts=PTS[v1];
    #   ...
    #   [v0][v1]xfade=transition=fade:duration=1:offset=<off>[vout0];
    #   [vout0][v2]xfade=transition=fade:duration=1:offset=<off>[vout1];
    #   ...
    #
    # Audio is NOT processed through acrossfade because the pre-rendered
    # clips have no audio stream.  If audio_path is provided, it is mapped
    # directly as an extra input.
    # ──────────────────────────────────────────────────────────────────

    filters: list[str] = []

    # 1. Scale each video input to target resolution
    for i in range(n):
        filters.append(
            f"[{i}:v]scale={output_w}:{output_h}:flags=lanczos,"
            f"setpts=PTS[v{i}]"
        )

    # 2. Chain xfade transitions
    #    prev_label starts as the first scaled input then tracks the
    #    last composite output as we chain.
    prev_label = "v0"
    for i in range(n - 1):
        t = transitions[i]
        trans_type = t.get("type", "fade")
        trans_dur = float(t.get("duration", 0.5))

        # offset = cumulative duration of clips[0..i] - transition_duration
        # The transition starts trans_dur seconds before clip[i] ends.
        offset = sum(clip_durations[:i + 1]) - trans_dur

        out_label = f"vout{i}"
        filters.append(
            f"[{prev_label}][v{i + 1}]"
            f"xfade=transition={trans_type}"
            f":duration={trans_dur}"
            f":offset={offset}"
            f"[{out_label}]"
        )
        prev_label = out_label

    filter_complex = ";".join(filters)
    last_video_label = f"[{prev_label}]"

    # ── Assemble ffmpeg command ───────────────────────────────────────
    cmd: list[str] = ["ffmpeg", "-y"]

    # Inputs — all video clips
    for p in clip_paths:
        cmd.extend(["-i", p])

    cmd.extend(["-filter_complex", filter_complex])

    # Map the final video composite
    cmd.extend(["-map", last_video_label])

    # Audio handling — separate input, no acrossfade needed
    if audio_path:
        # The audio input comes after all video inputs, so its stream
        # index is 'n' (0-based).
        cmd.extend(["-i", audio_path])
        cmd.extend(["-map", f"{n}:a", "-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.extend(["-an"])

    # Video encoding
    if hw_params:
        cmd.extend(hw_params)
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "veryfast"])

    cmd.extend([
        "-b:v", "4M",
        "-maxrate", "5M",
        "-bufsize", "5M",
        "-profile:v", "high",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        output_path,
    ])

    logger.debug("xconcat_clips ffmpeg command: %s", " ".join(cmd))
    ret, _, _ = _run_ffmpeg(cmd)
    if ret != 0:
        logger.error("xconcat_clips failed with return code %d", ret)
    return ret == 0
