import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

# Windows needs sync subprocess with CREATE_NO_WINDOW flag
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def _run_ffmpeg(cmd: list[str]) -> tuple[int, str, str]:
    """Run ffmpeg synchronously (in thread pool for async callers)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_SUBPROCESS_FLAGS,
    )
    stdout, stderr = proc.communicate()
    return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
MOVEMENTS = ['zoom_in', 'zoom_out', 'pan_right', 'pan_left', 'pan_up', 'pan_down']


class KenBurnsConfig:
    def __init__(
        self,
        filter_mode: str = "all",
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        intensity: float = 0.04,
        seed: int = 42,
        subtitles: bool = False,
    ):
        self.filter_mode = filter_mode
        self.width = width
        self.height = height
        self.fps = fps
        self.intensity = max(0.01, min(0.15, intensity))
        self.seed = seed
        self.subtitles = subtitles


def _normalize_str_for_match(t: str) -> str:
    t = t.lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(c for c in t if c.isalnum())
    return t


def _has_timestamps(fragments: list) -> bool:
    return all("start_time" in f and "end_time" in f for f in fragments)


def auto_match_timestamps(
    fragments_path: str,
    transcript_path: str,
    script_path: Optional[str] = None,
) -> int:
    """
    Auto-match fragment original_text against Whisper transcription.
    Mutates fragments JSON in-place, adding start_time/end_time.
    Returns number of matched fragments.
    """
    with open(fragments_path, "r", encoding="utf-8") as f:
        fragments = json.load(f)

    if _has_timestamps(fragments):
        return len(fragments)

    with open(transcript_path, "r", encoding="utf-8") as f:
        trans_raw = json.load(f)

    # Handle both formats: array or dict with "segments" key
    if isinstance(trans_raw, dict):
        segments = trans_raw.get("segments", [])
    elif isinstance(trans_raw, list):
        segments = trans_raw
    else:
        segments = []

    if not segments:
        return 0

    # Concatenate all segments for full transcript matching
    full_text = " ".join(s["text"] for s in segments if s.get("text"))
    all_words = []
    for s in segments:
        if s.get("words"):
            all_words.extend(s["words"])
    word_entries = [(w["text"], w["start"], w["end"]) for w in all_words if w.get("type") == "word"]

    norm_chars = []
    char_word_idx = []
    for wi, (text, _st, _et) in enumerate(word_entries):
        for c in text:
            nc = _normalize_str_for_match(c)
            if nc:
                norm_chars.append(nc)
                char_word_idx.append(wi)

    norm_trans = "".join(norm_chars)

    script_to_trans = {}
    if script_path and os.path.isfile(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            script_text = f.read()
        script_collapsed = " ".join(script_text.split())
        norm_script = _normalize_str_for_match(script_collapsed)
        from difflib import SequenceMatcher
        sm = SequenceMatcher(None, norm_script, norm_trans)
        for a, b, size in sm.get_matching_blocks():
            if size == 0:
                continue
            for offset in range(size):
                script_to_trans[a + offset] = b + offset

    matched = 0
    last_trans_pos = 0
    last_script_pos = 0
    prev_start_time = 0.0

    for frag in fragments:
        original = frag.get("original_text", "")
        frag_norm = _normalize_str_for_match(original)
        if not frag_norm:
            continue

        frag_matched = False

        pos = norm_trans.find(frag_norm, last_trans_pos)
        if pos == -1:
            from difflib import SequenceMatcher
            sm = SequenceMatcher(None, norm_trans, frag_norm)
            m = sm.find_longest_match(0, len(norm_trans), 0, len(frag_norm))
            if m.size >= len(frag_norm) * 0.6:
                pos = m.a
        if pos >= 0:
            end_pos = pos + len(frag_norm)
            indices = set()
            for p in range(pos, min(end_pos, len(char_word_idx))):
                wi = char_word_idx[p]
                if wi >= 0:
                    indices.add(wi)
            if indices:
                st = word_entries[min(indices)][1]
                if st >= prev_start_time - 2:
                    frag["start_time"] = st
                    frag["end_time"] = word_entries[max(indices)][2]
                    prev_start_time = st
                    matched += 1
                    last_trans_pos = end_pos
                    frag_matched = True

        if not frag_matched and script_to_trans:
            pos = norm_script.find(frag_norm, last_script_pos)
            if pos >= 0 and pos in script_to_trans:
                script_end = pos + len(frag_norm)
                ts = te = None
                for p in range(pos, script_end):
                    if p in script_to_trans:
                        if ts is None:
                            ts = script_to_trans[p]
                        te = script_to_trans[p]
                if ts is not None and te is not None:
                    te += 1
                    indices = set()
                    for p in range(ts, min(te, len(char_word_idx))):
                        wi = char_word_idx[p]
                        if wi >= 0:
                            indices.add(wi)
                    if indices:
                        st = word_entries[min(indices)][1]
                        et = word_entries[max(indices)][2]
                        if st >= prev_start_time - 2:
                            frag["start_time"] = st
                            frag["end_time"] = et
                            prev_start_time = st
                            matched += 1
                            frag_matched = True
                            last_trans_pos = te
                            last_script_pos = script_end

    with open(fragments_path, "w", encoding="utf-8") as f:
        json.dump(fragments, f, ensure_ascii=False, indent=2)

    return matched


def get_numbered_images(folder: str, filter_mode: str = "all") -> list[Path]:
    if not os.path.isdir(folder):
        return []
    items = []
    for fname in os.listdir(folder):
        if Path(fname).suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        m = re.search(r'(?:^|_)(\d+)', fname)
        if not m:
            continue
        num = int(m.group(1))

        if filter_mode == "all":
            items.append((num, Path(folder) / fname))
        elif filter_mode == "even" and num % 2 == 0:
            items.append((num, Path(folder) / fname))
        elif filter_mode == "odd" and num % 2 != 0:
            items.append((num, Path(folder) / fname))

    items.sort(key=lambda x: x[0])
    return [path for _, path in items]


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def load_timestamps(json_path: str, n_images: int, audio_duration: float) -> list[float]:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Filter fragments that have start_time (matched to transcript)
    timed = [f for f in data if f.get("start_time") is not None]

    if not timed:
        return [audio_duration / n_images] * n_images

    durations = []
    matched_durs = []
    for i, frag in enumerate(timed):
        if frag.get("start_time") is not None:
            if i < len(timed) - 1 and timed[i + 1].get("start_time") is not None:
                matched_durs.append(timed[i + 1]["start_time"] - frag["start_time"])
    avg_dur = sum(matched_durs) / len(matched_durs) if matched_durs else audio_duration / max(len(timed), n_images)

    for i, frag in enumerate(timed):
        frag_start = frag.get("start_time")
        if frag_start is not None:
            if i < len(timed) - 1:
                next_start = timed[i + 1].get("start_time")
                if next_start is not None:
                    dur = next_start - frag_start
                else:
                    dur = avg_dur
            else:
                dur = audio_duration - frag_start
        else:
            dur = avg_dur

        if dur <= 0:
            dur = avg_dur

        durations.append(dur)

    # If fewer timed fragments than images, pad remaining with average
    while len(durations) < n_images:
        durations.append(avg_dur)

    return durations[:n_images]


def _scale_cover(image_path: str, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    img = Image.open(image_path)
    img_ratio = img.width / img.height
    canvas_ratio = canvas_w / canvas_h

    if img_ratio > canvas_ratio:
        new_h = canvas_h
        new_w = int(new_h * img_ratio)
    else:
        new_w = canvas_w
        new_h = int(new_w / img_ratio)

    return new_w, new_h


def _zoompan_expr(movement: str, frames: int, out_w: int, out_h: int,
                  canvas_w: int, canvas_h: int, fps: int) -> str:
    zf = canvas_w / out_w
    mx = canvas_w - out_w
    my = canvas_h - out_h
    cx = mx / 2
    cy = my / 2

    d = frames - 1 if frames > 1 else 1
    T = f"on/{d}"
    eased = f"({T})*({T})*(3-2*({T}))"

    if movement == 'zoom_in':
        z = f"1+({zf}-1)*({eased})"
        x = f"(in_w - in_w/(1+({zf}-1)*({eased})))/2"
        y = f"(in_h - in_h/(1+({zf}-1)*({eased})))/2"
    elif movement == 'zoom_out':
        z = f"{zf}-({zf}-1)*({eased})"
        x = f"(in_w - in_w/({zf}-({zf}-1)*({eased})))/2"
        y = f"(in_h - in_h/({zf}-({zf}-1)*({eased})))/2"
    elif movement == 'pan_right':
        z = f"{zf}"
        x = f"{mx} * ({eased})"
        y = f"{cy}"
    elif movement == 'pan_left':
        z = f"{zf}"
        x = f"{mx} * (1-({eased}))"
        y = f"{cy}"
    elif movement == 'pan_up':
        z = f"{zf}"
        x = f"{cx}"
        y = f"{my} * ({eased})"
    else:  # pan_down
        z = f"{zf}"
        x = f"{cx}"
        y = f"{my} * (1-({eased}))"

    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={out_w}x{out_h}:fps={fps}"


def _detect_hw_encoder() -> tuple[str, list[str]]:
    try:
        nv = subprocess.run(
            ['nvidia-smi'], capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        if nv.returncode == 0:
            return 'h264_nvenc', [
                '-c:v', 'h264_nvenc',
                '-preset', 'p1',
                '-rc', 'vbr',
            ]
    except FileNotFoundError:
        pass

    try:
        enc = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        if 'h264_amf' in enc.stdout:
            return 'h264_amf', [
                '-c:v', 'h264_amf',
                '-preset', 'speed',
                '-quality', 'balanced',
            ]
    except FileNotFoundError:
        pass

    return 'libx264', ['-c:v', 'libx264', '-preset', 'veryfast']


async def render_kenburns_video(
    project_dir: str,
    config: KenBurnsConfig,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Optional[Path]:
    """Render Ken Burns video with full feature set from original project."""
    project_path = Path(project_dir)
    images_dir = project_path / "imagenes"
    audio_dir = project_path / "audio"
    output_dir = project_path / "render"
    temp_dir = project_path / "temp"

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    images = get_numbered_images(str(images_dir), config.filter_mode)
    if not images:
        logger.error(f"No images found with filter_mode={config.filter_mode}")
        return None

    n = len(images)

    audio_file = None
    for ext in [".mp3", ".wav", ".m4a"]:
        audio_candidates = list(audio_dir.glob(f"*{ext}"))
        if audio_candidates:
            audio_file = audio_candidates[0]
            break

    if audio_file:
        audio_duration = get_audio_duration(str(audio_file))
        total_duration = audio_duration
    else:
        total_duration = n * 5.0
        audio_duration = total_duration

    fragments_path = None
    transcript_path = None
    script_path = None

    prompts_files = list(project_path.glob("prompts-*.json"))
    if prompts_files:
        fragments_path = prompts_files[0]

    # Check for script.json in project root (Transcriptor format) or audio/ (our format)
    # Prefer root (Transcriptor) — better word-level precision for matching
    root_json = project_path / "script.json"
    if root_json.exists():
        transcript_path = str(root_json)
    else:
        audio_json = audio_dir / "script.json"
        if audio_json.exists():
            transcript_path = str(audio_json)

    script_txt = audio_dir / "reference.txt"
    if script_txt.exists():
        script_path = str(script_txt)
    if not script_path:
        root_txt = project_path / "text.txt"
        if root_txt.exists():
            script_path = str(root_txt)

    if fragments_path and transcript_path:
        if progress_callback:
            progress_callback(0.05, "Auto-matching timestamps...")
        matched = auto_match_timestamps(str(fragments_path), transcript_path, script_path)
        logger.info(f"Matched {matched}/{n} fragments to transcript")

    if fragments_path and fragments_path.exists():
        with open(fragments_path, "r", encoding="utf-8") as f:
            fragments_data = json.load(f)
        timestamps_path = str(fragments_path)
        durations = load_timestamps(timestamps_path, n, total_duration)
    else:
        durations = [total_duration / n] * n

    exact_frames = [d * config.fps for d in durations]
    cum_float = 0.0
    cum_int = 0
    frames_per_clip = []
    for ef in exact_frames:
        cum_float += ef
        rounded = round(cum_float)
        frames_per_clip.append(rounded - cum_int)
        cum_int = rounded

    total_frames = sum(frames_per_clip)

    out_w, out_h = config.width, config.height
    margin_x = int(out_w * config.intensity)
    margin_y = int(out_h * config.intensity)
    canvas_w = out_w + margin_x * 2
    canvas_h = out_h + margin_y * 2

    rng = random.Random(config.seed)
    movements = [rng.choice(MOVEMENTS) for _ in range(n)]

    hw_encoder, hw_params = _detect_hw_encoder()
    logger.info(f"Detected encoder: {hw_encoder}")

    if hw_encoder == 'h264_nvenc':
        clip_encoder = ['-c:v', 'h264_nvenc', '-preset', 'p1', '-qp', '18']
    elif hw_encoder == 'h264_amf':
        clip_encoder = ['-c:v', 'h264_amf', '-preset', 'speed', '-quality', 'balanced']
    else:
        clip_encoder = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18']

    render_w = out_w * 2
    render_h = out_h * 2
    render_margin_x = int(render_w * config.intensity)
    render_margin_y = int(render_h * config.intensity)
    render_canvas_w = render_w + render_margin_x * 2
    render_canvas_h = render_h + render_margin_y * 2

    clip_files = []

    for i, (img_path, movement) in enumerate(zip(images, movements)):
        if progress_callback:
            progress = 0.1 + 0.6 * (i / n)
            progress_callback(progress, f"Rendering clip {i+1}/{n}: {movement}")

        clip_name = f"clip_{i:04d}.mp4"
        clip_path = temp_dir / clip_name
        clip_files.append(clip_path)

        frames_each_i = frames_per_clip[i]
        sw, sh = _scale_cover(str(img_path), render_canvas_w, render_canvas_h)

        zp_expr = _zoompan_expr(movement, frames_each_i, render_w, render_h,
                                render_canvas_w, render_canvas_h, config.fps)

        cmd = [
            'ffmpeg', '-y',
            '-i', str(img_path),
            '-vf', f"scale={sw}:{sh},setsar=1,{zp_expr}",
        ]
        cmd.extend(clip_encoder)
        cmd.extend([
            '-pix_fmt', 'yuv420p',
            '-an',
            str(clip_path),
        ])

        loop = asyncio.get_running_loop()
        returncode, _, _ = await loop.run_in_executor(None, _run_ffmpeg, cmd)

        if returncode != 0:
            logger.error(f"FFmpeg error for {img_path}")
            continue

    if not clip_files:
        return None

    if progress_callback:
        progress_callback(0.75, "Concatenating clips...")

    concat_list = temp_dir / 'concat_list.txt'
    with open(concat_list, 'w', encoding='utf-8') as f:
        for clip in clip_files:
            abs_path = str(clip.resolve()).replace('\\', '/')
            f.write(f"file '{abs_path}'\n")

    output_path = output_dir / "output.mp4"

    final_cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', str(concat_list),
    ]

    if audio_file:
        final_cmd.extend(['-i', str(audio_file)])

    vf_scale = f'scale={out_w}:{out_h}:flags=lanczos'
    final_cmd.extend(['-vf', vf_scale])
    final_cmd.extend(hw_params)
    final_cmd.extend([
        '-b:v', '4M',
        '-maxrate', '5M',
        '-bufsize', '5M',
        '-profile:v', 'high',
        '-level', '4.0',
    ])

    if audio_file:
        final_cmd.extend([
            '-c:a', 'aac',
            '-b:a', '192k',
            '-t', str(total_duration),
        ])
    else:
        final_cmd.extend([
            '-t', str(total_duration),
        ])

    final_cmd.extend([
        '-pix_fmt', 'yuv420p',
        str(output_path),
    ])

    loop = asyncio.get_running_loop()
    returncode, _, _ = await loop.run_in_executor(None, _run_ffmpeg, final_cmd)

    if returncode != 0:
        logger.error("FFmpeg concat/encode failed")
        return None

    if config.subtitles:
        srt_file = audio_dir / "script.srt"
        if srt_file.exists():
            if progress_callback:
                progress_callback(0.9, "Burning subtitles...")

            # Convert SRT to ASS for reliable rendering (like shorts module)
            try:
                from app.services.shorts_maker.subtitler import create_subtitle_ass
                ass_path = temp_dir / "subtitles.ass"
                srt_copy = temp_dir / "script.srt"
                shutil.copy2(srt_file, srt_copy)
                create_subtitle_ass(
                    srt_copy,
                    ass_path,
                    video_width=config.width,
                    video_height=config.height,
                )

                sub_out = output_path.with_suffix('.tmp.mp4')
                escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")

                sub_cmd = [
                    'ffmpeg', '-y',
                    '-i', str(output_path),
                    '-vf', f"ass='{escaped_ass}'",
                ]
                sub_cmd.extend(hw_params)
                sub_cmd.extend([
                    '-b:v', '4M', '-maxrate', '5M', '-bufsize', '5M',
                    '-profile:v', 'high', '-level', '4.0',
                ])
                if audio_file:
                    sub_cmd.extend(['-c:a', 'copy'])
                sub_cmd.extend(['-pix_fmt', 'yuv420p', str(sub_out)])

                ret, _, sub_err = await loop.run_in_executor(None, _run_ffmpeg, sub_cmd)

                if ret == 0:
                    output_path.unlink()
                    sub_out.rename(output_path)
                    logger.info("[RENDER] Subtitles burned successfully (ASS)")
                else:
                    logger.warning("[RENDER] Subtitles failed: %.200s", sub_err)
            except Exception as e:
                logger.warning("[RENDER] Subtitles setup failed: %s", e)
        else:
            logger.warning("[RENDER] Subtitles enabled but no script.srt found in %s", audio_dir)

    shutil.rmtree(temp_dir, ignore_errors=True)

    if progress_callback:
        progress_callback(1.0, "Render complete")

    return output_path
