"""
timeline_renderer.py — Render a ``timeline.json`` to video.

Five-pass rendering pipeline
-----------------------------
  1. Render video clips sequentially  0 % → 60 %
  2. Gather rendered clips           60 % → 70 %
  3. Concat + audio                  70 % → 85 %
  4. Burn subtitles via ASS          85 % → 95 %
  5. Move output, clean up temp      95 % → 100 %

The timeline schema follows the CapCut-style format produced by
``timeline_migration.auto_migrate()``.  All relative ``source_path``
values in the timeline are resolved against the project directory.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Callable, Optional

from app.services.clip_renderer import (
    _detect_hw_encoder,
    _run_ffmpeg,
    concat_clips,
    render_image_clip,
    xconcat_clips,
)

logger = logging.getLogger(__name__)

# -- Constants ---------------------------------------------------------------

_INTENSITY_MIN = 0.01
"""Lower bound for the Ken Burns intensity parameter."""
_INTENSITY_MAX = 0.15
"""Upper bound for the Ken Burns intensity parameter."""


# -- Renderer ----------------------------------------------------------------


class TimelineRenderer:
    """Render a timeline dict to an MP4 video.

    Parameters
    ----------
    project_dir : str
        Root directory of the project.  All ``source_path`` values in
        the timeline that are relative paths are resolved against this.
    timeline : dict
        A timeline dict following the CapCut-style schema documented
        in :func:`timeline_migration.auto_migrate`.
    """

    def __init__(self, project_dir: str, timeline: dict) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.timeline = timeline
        self.temp_dir = self.project_dir / "temp"
        self.render_dir = self.project_dir / "render"

    # -- Public API ----------------------------------------------------------

    async def render(
        self,
        progress_callback: Callable[[float, str], None] | None = None,
        output_path: str | None = None,
    ) -> Path | None:
        """Run the five-pass rendering pipeline.

        Parameters
        ----------
        progress_callback : callable or None
            Called with ``(progress_0to1, message)`` at various stages
            of the pipeline so callers can show a progress bar.
        output_path : str or None
            Destination for the final MP4 file.  When ``None``, the
            output is written to ``{render_dir}/output.mp4``.

        Returns
        -------
        Path or None
            Absolute path to the completed video, or ``None`` when
            rendering fails (no video track, no clips, concat error,
            etc.).
        """
        try:
            return await self._render_impl(progress_callback, output_path)
        except asyncio.CancelledError:
            logger.warning("Render cancelled — cleaning up temp files")
            self._cleanup()
            raise

    # -- Pipeline ------------------------------------------------------------

    async def _render_impl(
        self,
        progress_callback: Callable[[float, str], None] | None = None,
        output_path: str | None = None,
    ) -> Path | None:
        canvas = self.timeline.get("canvas", {})
        canvas_w = canvas.get("width", 1920)
        canvas_h = canvas.get("height", 1080)
        fps = canvas.get("fps", 30)

        # ── Extract video track ─────────────────────────────────────────
        video_track: dict | None = None
        for track in self.timeline.get("tracks", []):
            if track.get("type") == "video":
                video_track = track
                break

        if video_track is None:
            logger.error("No video track found in timeline — nothing to render")
            return None

        clips: list[dict] = video_track.get("clips", [])
        if not clips:
            logger.error("Video track has no clips — nothing to render")
            return None

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        rendered_clip_paths: list[Path] = []
        total_clips = len(clips)
        loop = asyncio.get_running_loop()

        # ═══════════════════════════════════════════════════════════════
        # Pre-compute frame counts using cumulative rounding (matching
        # the original kenburns.py precision) to avoid per-clip drift
        # that desynchronises the video from the audio track.
        exact = [clip.get("duration", 5.0) * fps for clip in clips]
        cum_f: float = 0.0
        cum_i: int = 0
        frames_per_clip: list[int] = []
        for ef in exact:
            cum_f += ef
            rounded = round(cum_f)
            frames_per_clip.append(rounded - cum_i)
            cum_i = rounded

        # ═══════════════════════════════════════════════════════════════
        # PASS 1 — Render video clips  (0 % → 60 %)
        # ═══════════════════════════════════════════════════════════════
        for i, clip in enumerate(clips):
            if progress_callback:
                progress_callback(
                    (i / total_clips) * 0.6,
                    f"Rendering clip {i + 1}/{total_clips}",
                )

            source_type = clip.get("source_type", "image")
            if source_type != "image":
                logger.warning(
                    "Skipping clip %s: unsupported source_type=%r",
                    clip.get("id", "?"),
                    source_type,
                )
                continue

            # Resolve the source image path relative to the project dir
            img_rel = clip.get("source_path", "")
            img_path = self.project_dir / img_rel
            if not img_path.is_file():
                logger.warning(
                    "Skipping clip %s: image not found at %s",
                    clip.get("id", "?"),
                    img_path,
                )
                continue

            movement = clip.get("movement", "zoom_in")
            duration = clip.get("duration", 5.0)
            raw_intensity = clip.get("intensity", 0.05)
            intensity = max(_INTENSITY_MIN, min(_INTENSITY_MAX, raw_intensity))

            clip_name = f"clip_{i:04d}.mp4"
            clip_out = self.temp_dir / clip_name

            ok = await loop.run_in_executor(
                None,
                render_image_clip,
                str(img_path),
                movement,
                duration,
                fps,
                canvas_w,
                canvas_h,
                str(clip_out),
                intensity,
                frames_per_clip[i],
            )

            if ok:
                rendered_clip_paths.append(clip_out)
            else:
                logger.warning(
                    "Failed to render clip %s (%s) — skipping",
                    clip.get("id", "?"),
                    img_rel,
                )

        if not rendered_clip_paths:
            logger.error("No clips were successfully rendered")
            self._cleanup()
            return None

        # ═══════════════════════════════════════════════════════════════
        # PASS 2 — Gather rendered clips  (60 % → 70 %)
        # ═══════════════════════════════════════════════════════════════
        if progress_callback:
            progress_callback(0.65, f"Gathered {len(rendered_clip_paths)} clips")

        # Determine the audio path from the audio track
        audio_path: str | None = None
        for track in self.timeline.get("tracks", []):
            if track.get("type") == "audio" and not track.get("muted", False):
                audio_clips = track.get("clips", [])
                if audio_clips:
                    audio_rel = audio_clips[0].get("source_path", "")
                    if audio_rel:
                        audio_candidate = self.project_dir / audio_rel
                        if audio_candidate.is_file():
                            audio_path = str(audio_candidate.resolve())
                            break

        total_duration = self.timeline.get("duration")
        hw_encoder, hw_params = _detect_hw_encoder()
        logger.info("Detected encoder: %s", hw_encoder)

        # Resolve final output path
        if output_path is not None:
            final_output = Path(output_path).resolve()
        else:
            self.render_dir.mkdir(parents=True, exist_ok=True)
            final_output = self.render_dir / "output.mp4"
        final_output.parent.mkdir(parents=True, exist_ok=True)

        # ═══════════════════════════════════════════════════════════════
        # PASS 3 — Concat + audio  (70 % → 85 %)
        # ═══════════════════════════════════════════════════════════════
        # Detect whether any clip has a transition_out — if so, use
        # xconcat_clips (xfade filter_complex) instead of simple concat.
        # ──────────────────────────────────────────────────────────────
        has_transitions = any(
            clip.get("transition_out") is not None
            for clip in clips
        )

        if has_transitions:
            # Build transitions list and clip durations for xfade
            transition_list: list[dict] = []
            clip_durations: list[float] = []
            for clip in clips:
                clip_durations.append(clip["duration"])
                to = clip.get("transition_out")
                if to is not None:
                    transition_list.append(to)

            # Adjust total_duration for transition overlaps.
            # Each transition overlaps clip[i] ending with clip[i+1]
            # beginning, so the output is shorter by the sum of all
            # transition durations.
            total_transition_time = sum(
                t.get("duration", 0.0) for t in transition_list
            )
            adjusted_duration = (
                sum(clip_durations) - total_transition_time
            )

            if progress_callback:
                msg = (
                    f"Rendering {len(transition_list)} transition(s) "
                    + ("with audio" if audio_path else "")
                )
                progress_callback(0.72, msg)

            ok = await loop.run_in_executor(
                None,
                xconcat_clips,
                [str(p.resolve()) for p in rendered_clip_paths],
                clip_durations,
                str(final_output),
                transition_list,
                audio_path,
                hw_params,
                canvas_w,
                canvas_h,
                fps,
            )

            # Update total_duration so subsequent passes (subtitle burn)
            # use the correct trimmed length.
            total_duration = adjusted_duration
        else:
            if progress_callback:
                msg = "Concatenating clips" + (
                    " with audio" if audio_path else ""
                )
                progress_callback(0.72, msg)

            ok = await loop.run_in_executor(
                None,
                concat_clips,
                [str(p.resolve()) for p in rendered_clip_paths],
                str(final_output),
                audio_path,
                total_duration,
                hw_params,
                canvas_w,
                canvas_h,
            )

        if not ok:
            logger.error("Clip concatenation failed")
            self._cleanup()
            return None

        if progress_callback:
            progress_callback(0.85, "Concatenation done")

        # ═══════════════════════════════════════════════════════════════
        # PASS 4 — Burn subtitles  (85 % → 95 %)
        # ═══════════════════════════════════════════════════════════════
        srt_path: Path | None = None

        # Check the subtitle track first
        subtitle_track: dict | None = None
        for track in self.timeline.get("tracks", []):
            if track.get("type") == "subtitle":
                subtitle_track = track
                break

        # Try: unlocked track OR fallback to audio/script.srt on disk
        if subtitle_track is not None and not subtitle_track.get("locked", True):
            # Future: per-clip SRT reference from track clips
            pass

        script_srt = self.project_dir / "audio" / "script.srt"
        if script_srt.is_file():
            srt_path = script_srt

        if srt_path is not None:
            if progress_callback:
                progress_callback(0.88, "Burning subtitles...")

            try:
                from app.services.shorts_maker.subtitler import (
                    create_subtitle_ass,
                )

                ass_path = self.temp_dir / "subtitles.ass"
                create_subtitle_ass(
                    srt_path,
                    ass_path,
                    video_width=canvas_w,
                    video_height=canvas_h,
                )

                sub_out = final_output.with_suffix(".tmp.mp4")
                escaped_ass = (
                    str(ass_path).replace("\\", "/").replace(":", "\\:")
                )

                sub_cmd = [
                    "ffmpeg", "-y",
                    "-i", str(final_output),
                    "-vf", f"ass='{escaped_ass}'",
                ]
                sub_cmd.extend(hw_params)
                sub_cmd.extend([
                    "-b:v", "4M",
                    "-maxrate", "5M",
                    "-bufsize", "5M",
                    "-profile:v", "high",
                    "-level", "4.0",
                ])
                if audio_path:
                    sub_cmd.extend(["-c:a", "copy"])
                sub_cmd.extend(["-pix_fmt", "yuv420p", str(sub_out)])

                ret, _, sub_err = await loop.run_in_executor(
                    None, _run_ffmpeg, sub_cmd,
                )

                if ret == 0:
                    final_output.unlink(missing_ok=True)
                    sub_out.rename(final_output)
                    logger.info("Subtitles burned successfully (ASS)")
                else:
                    logger.warning(
                        "Subtitle burn failed (ffmpeg rc=%d): %.200s",
                        ret,
                        sub_err,
                    )
            except Exception:
                logger.warning("Subtitle setup failed", exc_info=True)
        else:
            logger.warning("No subtitle file found — skipping subtitle pass")

        # ═══════════════════════════════════════════════════════════════
        # PASS 5 — Finalize  (95 % → 100 %)
        # ═══════════════════════════════════════════════════════════════
        if progress_callback:
            progress_callback(0.96, "Cleaning up temporary files")

        self._cleanup()

        if progress_callback:
            progress_callback(1.0, "Render complete")

        return final_output.resolve()

    # -- Internal helpers ----------------------------------------------------

    def _cleanup(self) -> None:
        """Remove the temporary directory and all its contents."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
