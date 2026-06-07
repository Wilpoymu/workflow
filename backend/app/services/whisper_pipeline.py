import json
import logging
import re
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models.transcript import SrtBlock, TranscriptionSegment, WhisperWord

logger = logging.getLogger(__name__)


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


# ── Core transcription ─────────────────────────────────────────────


def transcribe_audio(
    audio_path: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> TranscriptionSegment:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.error("faster-whisper not installed")
        raise RuntimeError("faster-whisper not installed. Run: pip install faster-whisper")

    if progress_callback:
        progress_callback(0.1, "Loading model...")

    model = WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )

    if progress_callback:
        progress_callback(0.3, "Transcribing audio...")

    segments_gen, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language=None,
        beam_size=5,
    )

    logger.info(f"Detected language: {info.language} (prob: {info.language_probability:.2f})")

    all_words: list[WhisperWord] = []
    last_end: float = 0.0

    for seg in segments_gen:
        if progress_callback:
            progress = 0.3 + 0.6 * (seg.end / info.duration) if info.duration > 0 else 0.0
            progress_callback(progress, f"Transcribing... {int(progress * 100)}%")

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
                        text=" ", start=gap_start, end=gap_end, type="spacing",
                    ))

            all_words.append(WhisperWord(
                text=text,
                start=start,
                end=end,
                type="word",
                speaker_id="speaker_0",
                logprob=round(w.probability, 7) if w.probability is not None else 0.0,
            ))
            last_end = end

    full_text = " ".join(w.text for w in all_words if w.type == "word")

    if progress_callback:
        progress_callback(0.95, "Finalizing...")

    return TranscriptionSegment(
        language_code=info.language or "es",
        language_probability=info.language_probability,
        text=full_text,
        words=all_words,
    )


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
