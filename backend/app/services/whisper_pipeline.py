import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

ProgressCB = Callable[[float, str, dict[str, Any] | None], None] | None

from app.config import settings
from app.models.transcript import SrtBlock, TranscriptionSegment, WhisperWord

logger = logging.getLogger(__name__)

# Audio más largo que esto se parte en fragmentos antes de transcribir
_MAX_CHUNK_SECONDS = 1200  # 20 minutos

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


# ── SRT generation (sentence-based, same as Transcriptor) ─────────

_SENTENCE_END_RE = re.compile(r"[.!?]$")
_COMMA_END_RE = re.compile(r",$")


def generate_srt(words: list[WhisperWord], max_chars: int = 100) -> list[SrtBlock]:
    word_tokens = [w for w in words if w.type == "word"]
    blocks: list[SrtBlock] = []
    buffer: list[WhisperWord] = []

    for wt in word_tokens:
        tentative = buffer + [wt]
        tentative_text = " ".join(w.text for w in tentative)
        tentative_len = len(tentative_text)

        is_sentence_end = bool(_SENTENCE_END_RE.search(wt.text))
        ends_with_comma = bool(_COMMA_END_RE.search(wt.text))
        near_limit = tentative_len > int(max_chars * 0.85)

        if is_sentence_end and tentative_len <= max_chars:
            buffer.append(wt)
            blocks.append(_make_block(len(blocks) + 1, buffer))
            buffer = []
            continue

        if near_limit and ends_with_comma:
            buffer.append(wt)
            blocks.extend(_split_at_last_comma(len(blocks) + 1, buffer))
            buffer = []
            continue

        if tentative_len > max_chars:
            if buffer:
                blocks.append(_make_block(len(blocks) + 1, buffer))
            buffer = [wt]
            continue

        buffer.append(wt)

    if buffer:
        blocks.append(_make_block(len(blocks) + 1, buffer))

    for i, blk in enumerate(blocks, start=1):
        blk.index = i

    return blocks


def _make_block(index: int, words: list[WhisperWord]) -> SrtBlock:
    text = " ".join(w.text for w in words)
    return SrtBlock(
        index=index,
        start=words[0].start,
        end=words[-1].end,
        text=text,
    )


def _split_at_last_comma(start_index: int, buffer: list[WhisperWord]) -> list[SrtBlock]:
    split_at = None
    for i in range(len(buffer) - 1, 0, -1):
        if _COMMA_END_RE.search(buffer[i].text):
            split_at = i
            break
    if split_at is None:
        return [_make_block(start_index, buffer)]

    before = buffer[: split_at + 1]
    after = buffer[split_at + 1 :]
    blocks = [_make_block(start_index, before)]
    if after:
        blocks.append(_make_block(start_index + 1, after))
    return blocks


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_to_string(blocks: list[SrtBlock]) -> str:
    entries: list[str] = []
    for blk in blocks:
        start_ts = _format_srt_time(blk.start)
        end_ts = _format_srt_time(blk.end)
        entries.append(f"{blk.index}\n{start_ts} --> {end_ts}\n{blk.text}")
    return "\n\n".join(entries) + "\n"


# ── Text alignment (Needleman-Wunsch, from Transcriptor) ──────────

_MATCH = 2
_FUZZY = 1
_MISMATCH = -1
_GAP = -1


def _normalize_word(word: str) -> str:
    return re.sub(r"[^\w]", "", word).lower()


def _score_pair(whisper_word: str, text_word: str) -> int:
    w = _normalize_word(whisper_word)
    t = _normalize_word(text_word)
    if not w or not t:
        return _MISMATCH
    if w == t:
        return _MATCH
    n = min(3, len(w), len(t))
    if n > 0 and w[:n] == t[:n]:
        return _FUZZY
    return _MISMATCH


def _tokenize_text(text: str) -> list[str]:
    return text.split()


def align_text(whisper_words: list[WhisperWord], text_content: str) -> list[WhisperWord]:
    w_words = [w for w in whisper_words if w.type == "word"]
    if not w_words:
        result: list[WhisperWord] = []
        for i, token in enumerate(text_content.split()):
            if result:
                result.append(WhisperWord(text=" ", start=i * 0.2, end=i * 0.2 + 0.05, type="spacing"))
            result.append(WhisperWord(text=token, start=i * 0.2 + 0.05, end=i * 0.2 + 0.2))
        return result

    text_tokens = _tokenize_text(text_content)
    w_texts = [w.text for w in w_words]
    n = len(w_texts)
    m = len(text_tokens)

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    tb = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + _GAP
        tb[i][0] = 1
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + _GAP
        tb[0][j] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + _score_pair(w_texts[i - 1], text_tokens[j - 1])
            up = dp[i - 1][j] + _GAP
            left = dp[i][j - 1] + _GAP
            if diag >= up and diag >= left:
                dp[i][j] = diag
                tb[i][j] = 0
            elif up >= left:
                dp[i][j] = up
                tb[i][j] = 1
            else:
                dp[i][j] = left
                tb[i][j] = 2

    alignment: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and tb[i][j] == 0:
            alignment.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and tb[i][j] == 1:
            alignment.append((i - 1, None))
            i -= 1
        elif j > 0 and tb[i][j] == 2:
            alignment.append((None, j - 1))
            j -= 1
        elif i > 0:
            alignment.append((i - 1, None))
            i -= 1
        elif j > 0:
            alignment.append((None, j - 1))
            j -= 1
    alignment.reverse()

    entries: list[tuple[int, float | None, float | None]] = []
    for w_idx, t_idx in alignment:
        if t_idx is None:
            continue
        if w_idx is not None:
            ww = w_words[w_idx]
            entries.append((t_idx, ww.start, ww.end))
        else:
            entries.append((t_idx, None, None))

    pos = 0
    while pos < len(entries):
        _, start, _ = entries[pos]
        if start is not None:
            pos += 1
            continue
        gap_start = pos
        while pos < len(entries) and entries[pos][1] is None:
            pos += 1
        gap_end = pos
        prev_end = entries[gap_start - 1][2] if gap_start > 0 else 0.0
        next_start = entries[gap_end][1] if gap_end < len(entries) else None
        gap_size = gap_end - gap_start
        if next_start is None:
            for k in range(gap_start, gap_end):
                s = prev_end + 0.1 * (k - gap_start + 1)
                entries[k] = (entries[k][0], round(s, 3), round(s + 0.15, 3))
        else:
            total_gap = next_start - prev_end
            if total_gap <= 0:
                total_gap = 0.1 * gap_size
            chunk = total_gap / (gap_size + 1)
            for k in range(gap_start, gap_end):
                offset = k - gap_start + 1
                s = prev_end + chunk * offset
                entries[k] = (entries[k][0], round(s, 3), round(s + chunk * 0.6, 3))

    result: list[WhisperWord] = []
    last_end = 0.0
    for t_idx, start, end in entries:
        text = text_tokens[t_idx]
        if result:
            gap_tok = WhisperWord(
                text=" ", start=round(last_end, 3), end=round(start, 3), type="spacing",
            )
            if gap_tok.end > gap_tok.start:
                result.append(gap_tok)
        result.append(WhisperWord(text=text, start=round(start, 3), end=round(end, 3)))
        last_end = end

    return result


# ── Audio chunking —──────────────────────────────────────────────────


def _get_audio_duration_ffprobe(audio_path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', audio_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"ffprobe failed for {audio_path}: {proc.stderr.strip()}")
    return float(proc.stdout.strip())


def _split_audio(audio_path: str, chunk_sec: int, work_dir: str) -> list[str]:
    duration = _get_audio_duration_ffprobe(audio_path)
    if duration <= chunk_sec:
        return [audio_path]

    n_chunks = math.ceil(duration / chunk_sec)
    paths: list[str] = []
    base = Path(audio_path)
    stem = base.stem
    ext = base.suffix

    for i in range(n_chunks):
        start = i * chunk_sec
        chunk_path = os.path.join(work_dir, f"{stem}_chunk{i:04d}{ext}")
        cmd = [
            'ffmpeg', '-y',
            '-i', audio_path,
            '-ss', str(start),
            '-t', str(chunk_sec),
            '-c', 'copy',
            chunk_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, creationflags=_SUBPROCESS_FLAGS)
        if proc.returncode != 0:
            raise RuntimeError(f"Audio chunking failed at chunk {i}: {proc.stderr.decode(errors='replace')[:200]}")
        paths.append(chunk_path)

    logger.info("[WHISPER] Audio split into %d chunks (%.0fs each)", n_chunks, chunk_sec)
    return paths


def _merge_chunks(segments: list[TranscriptionSegment]) -> TranscriptionSegment:
    all_words: list[WhisperWord] = []
    full_texts: list[str] = []

    for seg in segments:
        all_words.extend(seg.words)
        full_texts.append(seg.text)

    return TranscriptionSegment(
        language_code=segments[0].language_code,
        language_probability=segments[0].language_probability,
        text=" ".join(full_texts),
        words=all_words,
    )


# ── Device detection (NVIDIA → CPU) ──────────────────────────────────


def _ensure_cuda_dlls_on_path():
    if os.name != "nt":
        return
    try:
        import nvidia.cublas
        pkg_dir = nvidia.cublas.__path__[0]
        bin_dir = os.path.join(pkg_dir, "bin")
        if os.path.isdir(bin_dir) and bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            logger.info("[WHISPER] Added %s to PATH (CUDA DLLs)", bin_dir)
    except Exception:
        pass


def _detect_whisper_device() -> tuple[str, str]:
    _ensure_cuda_dlls_on_path()
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
        if count > 0:
            logger.info("[WHISPER] CUDA detected (%d device(s)) — using GPU", count)
            return "cuda", "float16"
    except Exception:
        pass

    logger.info("[WHISPER] No CUDA device — falling back to CPU (int8)")
    return "cpu", "int8"


# ── Core transcription ─────────────────────────────────────────────


def _transcribe_single(
    model,
    audio_path: str,
    chunk_offset: float,
    progress_callback: ProgressCB = None,
    progress_start: float = 0.0,
    progress_end: float = 1.0,
) -> TranscriptionSegment:
    segments_gen, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language=None,
        beam_size=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    all_words: list[WhisperWord] = []
    last_end: float = 0.0
    duration = info.duration or 0.0

    for seg in segments_gen:
        if progress_callback and duration > 0:
            p = progress_start + (progress_end - progress_start) * (seg.end / duration)
            progress_callback(p, "Transcribing audio", {
                "stage": "transcribing",
            })

        if not seg.words:
            continue

        for w in seg.words:
            text = (w.word or "").strip()
            if not text:
                continue

            start = w.start if w.start is not None and w.start >= 0.0 else last_end
            end = w.end if w.end is not None and w.end >= start else start + 0.1

            if all_words:
                gap_start = last_end
                gap_end = start
                if gap_end > gap_start:
                    all_words.append(WhisperWord(
                        text=" ", start=gap_start + chunk_offset, end=gap_end + chunk_offset, type="spacing",
                    ))

            all_words.append(WhisperWord(
                text=text,
                start=start + chunk_offset,
                end=end + chunk_offset,
                type="word",
                speaker_id="speaker_0",
                logprob=round(w.probability, 7) if w.probability is not None else 0.0,
            ))
            last_end = end

    full_text = " ".join(w.text for w in all_words if w.type == "word")

    return TranscriptionSegment(
        language_code=info.language or "es",
        language_probability=info.language_probability,
        text=full_text,
        words=all_words,
    )


MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


def transcribe_audio(
    audio_path: str,
    progress_callback: ProgressCB = None,
    model_size: str | None = None,
) -> TranscriptionSegment:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.error("faster-whisper not installed")
        raise RuntimeError("faster-whisper not installed. Run: pip install faster-whisper")

    dur_str = ""
    try:
        dur = _get_audio_duration_ffprobe(audio_path)
        m, s = divmod(int(dur), 60)
        h, m = divmod(m, 60)
        dur_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
    except Exception:
        pass

    if progress_callback:
        msg = f"Checking audio... {dur_str}" if dur_str else "Checking audio duration..."
        progress_callback(0.02, msg, {"stage": "checking", "audio_duration_sec": dur})

    # Partir audio largo en fragmentos para evitar OOM
    work_dir = tempfile.mkdtemp(prefix="whisper_chunks_")
    try:
        chunk_paths = _split_audio(audio_path, _MAX_CHUNK_SECONDS, work_dir)
    except Exception:
        chunk_paths = [audio_path]

    model_name = model_size if model_size in MODEL_SIZES else settings.whisper_model_size
    device, compute_type = _detect_whisper_device()

    # Intentar GPU; si falta cublas/cuda, caer a CPU automáticamente
    for attempt in range(2):
        if progress_callback:
            progress_callback(0.05, f"Loading {model_name} on {device} ({compute_type})...", {
                "stage": "loading",
                "model": model_name,
                "device": device,
                "compute_type": compute_type,
            })

        try:
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            break
        except (OSError, RuntimeError) as e:
            err_str = str(e).lower()
            if device == "cuda" and ("cublas" in err_str or "cuda" in err_str or "driver" in err_str):
                logger.warning("[WHISPER] CUDA load failed (%s) — falling back to CPU", e)
                device, compute_type = "cpu", "int8"
                continue
            raise

    logger.info("[WHISPER] device=%s compute_type=%s model=%s chunks=%d",
                device, compute_type, model_name, len(chunk_paths))

    try:
        n_chunks = len(chunk_paths)

        if n_chunks == 1:
            result = _transcribe_single(model, chunk_paths[0], 0.0, progress_callback, 0.1, 0.95)
            if progress_callback:
                progress_callback(0.95, "Finalizing...", {"stage": "finalizing"})
            return result

        # Múltiples fragmentos
        if progress_callback:
            progress_callback(0.08, f"Splitting audio into {n_chunks} chunks ({_MAX_CHUNK_SECONDS // 60}min each)...", {
                "stage": "splitting",
                "chunks_total": n_chunks,
                "chunk_duration_sec": _MAX_CHUNK_SECONDS,
            })

        chunk_segments: list[TranscriptionSegment] = []
        chunk_dur = _get_audio_duration_ffprobe(chunk_paths[0]) if n_chunks > 0 else _MAX_CHUNK_SECONDS
        time_offset = 0.0

        for i, chunk_path in enumerate(chunk_paths):
            if progress_callback:
                cb_start = 0.1 + 0.8 * (i / n_chunks)
                cb_end = 0.1 + 0.8 * ((i + 1) / n_chunks)
            else:
                cb_start = cb_end = 0.0

            if progress_callback:
                progress_callback(cb_start, f"Chunk {i + 1}/{n_chunks} — transcribing...", {
                    "stage": "chunk",
                    "model": model_name,
                    "device": device,
                    "compute_type": compute_type,
                    "chunk_current": i + 1,
                    "chunks_total": n_chunks,
                })

            logger.info("[WHISPER] Transcribing chunk %d/%d: %s", i + 1, n_chunks, chunk_path)
            seg = _transcribe_single(model, chunk_path, time_offset,
                                     progress_callback, cb_start, cb_end)
            chunk_segments.append(seg)
            time_offset += chunk_dur

        if progress_callback:
            progress_callback(0.92, f"Merging {n_chunks} chunks...", {"stage": "merging"})

        result = _merge_chunks(chunk_segments)

        if progress_callback:
            lang = result.language_code or "es"
            prob = result.language_probability
            prob_safe = round(prob, 4) if prob is not None and not (prob != prob) else None
            prob_str = f"{prob_safe:.0%}" if prob_safe and prob_safe > 0 else ""
            progress_callback(0.95, f"Detected: {lang} {prob_str}".strip(), {
                "stage": "finalizing",
                "language": lang,
                "language_probability": prob_safe,
                "word_count": len(result.words),
            })

        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Save outputs (Transcriptor-compatible format) ──────────────────


def save_transcription(
    project_dir: str,
    segment: TranscriptionSegment,
    text_path: str | None = None,
) -> dict:
    project_path = Path(project_dir)
    audio_dir = project_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    words = segment.words

    # Optional: align with reference text to correct Whisper errors
    if text_path:
        ref_path = Path(text_path)
        if ref_path.exists():
            text_content = ref_path.read_text(encoding="utf-8")
            words = align_text(words, text_content)

    # Generate sentence-based SRT
    srt_blocks = generate_srt(words)
    srt_content = srt_to_string(srt_blocks)

    srt_path = audio_dir / "script.srt"
    srt_path.write_text(srt_content, encoding="utf-8")

    # Also save to project root for compatibility with Transcriptor-aware tools
    root_srt = project_path / "script.srt"
    root_srt.write_text(srt_content, encoding="utf-8")

    # Build JSON in Transcriptor's array format
    full_text = " ".join(w.text for w in words if w.type == "word")
    words_array = []
    for w in words:
        entry = {"text": w.text, "start": w.start, "end": w.end, "type": w.type, "speaker_id": w.speaker_id}
        entry["logprob"] = w.logprob if w.logprob is not None else 0.0
        words_array.append(entry)

    script_data = [{
        "language_code": segment.language_code or "es",
        "language_probability": segment.language_probability,
        "text": full_text,
        "words": words_array,
    }]

    json_path = audio_dir / "script.json"
    json_path.write_text(json.dumps(script_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also save to project root
    root_json = project_path / "script.json"
    root_json.write_text(json.dumps(script_data, ensure_ascii=False, indent=2), encoding="utf-8")

    word_count = sum(1 for w in words if w.type == "word")

    return {
        "srt_path": str(srt_path) + " (also in root)",
        "json_path": str(json_path) + " (also in root)",
        "word_count": word_count,
        "language": segment.language_code or "es",
        "segment_count": len(srt_blocks),
    }
