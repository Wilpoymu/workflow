"""Regression tests: reference script lookup + alignment in save_transcription.

Bug: run_transcription() looked for ``<project>/text.txt`` while save_script()
writes ``<project>/audio/text.txt``, so ``text_path_arg`` was always None and
``align_text()`` never ran — script.srt kept the raw ASR text ("20" instead of
"veinte", missing accents, etc.).

These tests lock the fix: a single helper resolves the reference text and
``save_transcription()`` aligns the Whisper words to it.
"""
from pathlib import Path

from app.models.transcript import TranscriptionSegment, WhisperWord
from app.services.project_service import get_reference_text_path
from app.services.whisper_pipeline import save_transcription

SCRIPT_TEXT = "veinte treinta qué tal, cuarenta y cinco cuarenta."

# Raw ASR output: numbers as digits, accents dropped.
ASR_WORDS = ["20", "30", "que", "tal,", "40", "y", "5", "40."]

LAST_WORD_END = 696.0  # 00:11:36,000 — the real audio's tail


def _segment(words: list[str]) -> TranscriptionSegment:
    """Build a segment with even 0.5 s steps: first word at 0.0, tail at 696.0."""
    step = LAST_WORD_END / len(words)
    whisper_words = [
        WhisperWord(text=token, start=round(i * step, 3), end=round((i + 1) * step, 3))
        for i, token in enumerate(words)
    ]
    return TranscriptionSegment(words=whisper_words, text=" ".join(words))


def _parse_srt(srt_content: str) -> list[tuple[str, str, str]]:
    """Return (start_ts, end_ts, text) per block."""
    blocks = []
    for raw_block in srt_content.strip().split("\n\n"):
        lines = raw_block.splitlines()
        start_ts, end_ts = (part.strip() for part in lines[1].split("-->"))
        blocks.append((start_ts, end_ts, " ".join(lines[2:])))
    return blocks


class TestGetReferenceTextPath:
    def test_resolves_in_documented_order(self, tmp_path: Path):
        assert get_reference_text_path(tmp_path) is None

        root_ref = tmp_path / "reference.txt"
        root_ref.write_text("root reference", encoding="utf-8")
        assert get_reference_text_path(tmp_path) == root_ref

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        audio_ref = audio_dir / "reference.txt"
        audio_ref.write_text("audio reference", encoding="utf-8")
        assert get_reference_text_path(tmp_path) == audio_ref

        root_txt = tmp_path / "text.txt"
        root_txt.write_text("root text", encoding="utf-8")
        assert get_reference_text_path(tmp_path) == root_txt

        audio_txt = audio_dir / "text.txt"
        audio_txt.write_text("audio text", encoding="utf-8")
        assert get_reference_text_path(tmp_path) == audio_txt


class TestSaveTranscriptionAlignment:
    def test_aligns_with_audio_text_only(self, tmp_path: Path):
        """Only audio/text.txt exists — the canonical save_script() location."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "text.txt").write_text(SCRIPT_TEXT, encoding="utf-8")

        text_path = get_reference_text_path(tmp_path)
        assert text_path == audio_dir / "text.txt"

        save_transcription(str(tmp_path), _segment(ASR_WORDS), str(text_path))

        srt_content = (audio_dir / "script.srt").read_text(encoding="utf-8")
        blocks = _parse_srt(srt_content)

        # Tokens and order match the script, not the raw ASR text.
        srt_tokens = " ".join(text for _, _, text in blocks).split()
        assert srt_tokens == SCRIPT_TEXT.split()
        assert "20" not in srt_content and "veinte" in srt_content

        # Whisper timings untouched: first block at 00:00:00, last ends at 11:36.
        assert blocks[0][0] == "00:00:00,000"
        assert blocks[-1][1] == "00:11:36,000"

    def test_aligns_with_legacy_root_text(self, tmp_path: Path):
        """Legacy project: the script still lives in the project root."""
        (tmp_path / "text.txt").write_text(SCRIPT_TEXT, encoding="utf-8")

        text_path = get_reference_text_path(tmp_path)
        assert text_path == tmp_path / "text.txt"

        save_transcription(str(tmp_path), _segment(ASR_WORDS), str(text_path))

        srt_content = (tmp_path / "audio" / "script.srt").read_text(encoding="utf-8")
        blocks = _parse_srt(srt_content)

        srt_tokens = " ".join(text for _, _, text in blocks).split()
        assert srt_tokens == SCRIPT_TEXT.split()
        assert blocks[0][0] == "00:00:00,000"
        assert blocks[-1][1] == "00:11:36,000"
