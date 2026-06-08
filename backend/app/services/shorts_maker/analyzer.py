from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.shorts_maker.srt_parser import entries_in_range, entries_text, parse_srt
from app.services.shorts_maker.types import ClipSuggestion

_HOOK_PHRASES = [
    r"necesito\s+que\s+me\s+escuches", r"presta\s+mucha?\s+atencion",
    r"esto\s+es\s+para\s+(vos|ti)", r"no\s+es\s+un\s+video\s+mas",
    r"no\s+es\s+casualidad", r"has\s+sentido", r"has\s+notado",
    r"te\s+has\s+preguntado", r"escucha\s+con\s+atencion",
    r"esto\s+te\s+interesa", r"lo\s+que\s+te\s+voy\s+a\s+contar",
    r"preparate?\s+porque", r"esto\s+apenas\s+comienza",
    r"ha\s+llegado\s+tu\s+momento", r"dejame\s+decirte",
    r"el\s+universo\s+todavia\s+no\s+ha\s+terminado",
]

_KEYWORDS = [
    r"\bamor\b", r"\bdinero\b", r"\bsalud\b", r"\btrabajo\b",
    r"\bfinanzas?\b", r"\babundancia\b", r"\bprosperidad\b",
    r"\btransformacion\b", r"\bpoder\b", r"\beconomi[ac]",
    r"\blaboral\b", r"\bprofesional\b", r"\bespiritual\b",
    r"\bcreatividad\b", r"\bintuicion\b",
]

_POWER_PHRASES = [
    r"tu\s+momento", r"tu\s+año", r"tu\s+mes", r"eres?\s+capaz",
    r"el\s+universo\s+(te\s+)?(dice|preparo|tiene|esta)",
    r"no\s+te\s+rindas", r"confia\s+en\s+(vos|ti|el\s+universo)",
    r"mereces?", r"imparable", r"poderoso", r"grandioso",
    r"extraordinario", r"increible", r"sorprendente",
    r"vale\s+la\s+pena", r"no\s+es\s+casualidad",
]

_CALL_TO_ACTION = [
    r"suscribete", r"suscrib[ií]te", r"campanita",
    r"comparte?\s+este\s+(video|mensaje)", r"deja\s+tu\s+like",
    r"comenta?\s+abajo", r"cuentamelo\s+en\s+los\s+comentarios",
    r"dimelo\s+en\s+los\s+comentarios", r"nos\s+vemos\s+en\s+el\s+proximo\s+video",
]

_SIGNS = [
    "aries", "tauro", "geminis", "cancer", "leo", "virgo",
    "libra", "escorpio", "sagitario", "capricornio", "acuario", "piscis",
]

_SIGN_VARIANTS = {
    "geminis": ["geminis", "géminis"],
    "cancer": ["cancer", "cáncer"],
}


def _score_text(text: str, position_ratio: float) -> float:
    tl = text.lower()
    s = 0.0
    for p in _HOOK_PHRASES:
        if re.search(p, tl): s += 4.0
    for p in _KEYWORDS:
        if re.search(p, tl): s += 2.0
    for p in _POWER_PHRASES:
        if re.search(p, tl): s += 3.0
    for p in _CALL_TO_ACTION:
        if re.search(p, tl): s += 1.5
    s += text.count("?") * 2.0 + text.count("¿") * 2.0
    s += text.count("!") * 1.0 + text.count("¡") * 1.0
    if position_ratio < 0.12: s += 3.0
    elif position_ratio > 0.85: s += 1.5
    wc = len(text.split())
    if 25 <= wc <= 90: s += 2.0
    elif 90 < wc <= 140: s += 1.0
    return s


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\sáéíóúüñ]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _load_word_timestamps(folder: Path) -> list[dict] | None:
    # Check root first, then audio/ subdirectory
    sj = folder / "script.json"
    if not sj.exists():
        audio_dir = folder / "audio"
        if audio_dir.is_dir():
            sj = audio_dir / "script.json"
    if not sj.exists():
        return None
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
        words = []
        for item in data:
            if isinstance(item, dict):
                if item.get("type") == "word" and item.get("text", "").strip():
                    words.append({"text": item["text"].strip(), "start": float(item.get("start", 0)), "end": float(item.get("end", 0))})
                elif "words" in item:
                    for w in item.get("words", []):
                        if w.get("type") == "word" and w.get("text", "").strip():
                            words.append({"text": w["text"].strip(), "start": float(w.get("start", 0)), "end": float(w.get("end", 0))})
        return words if words else None
    except Exception:
        return None


def _find_natural_boundary(entries: list, t_start: float, t_end: float, words=None) -> tuple[float, float]:
    window = [e for e in entries if e.end_sec > t_start - 3 and e.start_sec < t_end + 3]
    if not window:
        return t_start, t_end
    se = window[0]
    ee = window[-1]
    for e in window:
        if abs(e.start_sec - t_start) < abs(se.start_sec - t_start):
            se = e
        if abs(e.end_sec - t_end) < abs(ee.end_sec - t_end):
            ee = e
    return se.start_sec, ee.end_sec


def _find_sentence_start(entries: list, start_idx: int) -> int:
    """Walk backward from start_idx to find entry that starts a sentence.
    
    An entry starts a sentence if:
    - The previous entry ends with sentence-ending punctuation (. ! ? "...")
    - OR it's the very first entry
    - OR it starts with a capital letter (new sentence marker)
    """
    for i in range(start_idx, -1, -1):
        if i == 0:
            return 0
        prev_text = entries[i - 1].text.strip()
        if prev_text and prev_text[-1] in ".!?\"\u2026":
            return i
    return max(0, start_idx)


def _find_sentence_end(entries: list, end_idx: int) -> int:
    """Walk forward from end_idx to find entry that ends a sentence."""
    for i in range(end_idx, len(entries)):
        text = entries[i].text.strip()
        if text and text[-1] in ".!?\"\u2026":
            return i
    return min(len(entries) - 1, end_idx)


def _detect_section(text: str) -> str | None:
    """Detect if text starts with a zodiac sign name."""
    pl = _normalize(text)
    for sign in _SIGNS:
        variants = _SIGN_VARIANTS.get(sign, [sign])
        for v in variants:
            if re.match(rf"^{v}[,.\s]", pl):
                return sign
    return None


def _find_paragraph_in_srt(
    paragraph: str,
    entries: list,
    start_from: int = 0,
) -> int:
    """Find the first SRT entry whose normalized text contains the paragraph's first words."""
    snip = _normalize(paragraph)
    words = snip.split()
    if not words:
        return -1

    # Try with first 8 words
    for i in range(start_from, len(entries)):
        etext = _normalize(entries[i].text)
        match_words = words[:min(8, len(words))]
        if all(w in etext for w in match_words):
            return i

    # Fallback: match just first 3 words
    for i in range(start_from, len(entries)):
        etext = _normalize(entries[i].text)
        if all(w in etext for w in words[:3]):
            return i

    return -1


def _find_sign_in_srt(
    sign: str,
    entries: list,
    start_from: int = 0,
) -> int:
    """Find the first SRT entry that mentions this sign name."""
    variants = _SIGN_VARIANTS.get(sign, [sign])
    for i in range(start_from, len(entries)):
        etext = _normalize(entries[i].text)
        for v in variants:
            if re.search(rf"\b{v}\b", etext):
                return i
    return -1


def _build_segments(
    text_paragraphs: list[str],
    entries: list,
    total_duration: float,
) -> list[dict]:
    """Build segments by matching text.txt paragraphs directly to SRT entries.

    For each paragraph, find its position in SRT entries using text matching.
    Each segment's end is capped by the next paragraph's start or 60s max.
    """
    segments = []
    para_entry_indices: list[int] = []

    # Phase 1: find each paragraph's starting SRT entry index
    last_idx = 0
    for para in text_paragraphs:
        idx = _find_paragraph_in_srt(para, entries, start_from=last_idx)

        # Fallback: if paragraph starts with a sign, try to find sign mention
        if idx < 0:
            section = _detect_section(para)
            if section:
                idx = _find_sign_in_srt(section, entries, start_from=last_idx)

        if idx >= 0:
            para_entry_indices.append(idx)
            last_idx = idx
        else:
            # Could not find — still add a placeholder so we can skip later
            para_entry_indices.append(-1)

    # Phase 2: build segments from matched paragraphs
    for i, idx in enumerate(para_entry_indices):
        if idx < 0:
            continue

        section = _detect_section(text_paragraphs[i]) or ""

        # Snap start to sentence boundary (walk backward)
        sent_start_idx = _find_sentence_start(entries, idx)
        start_sec = entries[sent_start_idx].start_sec

        # Find end: next paragraph's match in SRT, or cap at 60s
        next_idx = -1
        for j in range(i + 1, len(para_entry_indices)):
            if para_entry_indices[j] > idx:
                next_idx = para_entry_indices[j]
                break

        if next_idx > idx:
            end_idx = next_idx - 1
        else:
            end_idx = min(idx + 30, len(entries) - 1)

        if end_idx <= idx:
            end_idx = min(idx + 25, len(entries) - 1)

        # Cap at 90s by trimming entries from the end
        while entries[end_idx].end_sec - start_sec > 90 and end_idx > sent_start_idx + 3:
            end_idx -= 1
        end_sec = entries[end_idx].end_sec

        # Snap end to sentence boundary (walk forward, but don't exceed 90s)
        snap_idx = _find_sentence_end(entries, end_idx)
        if snap_idx > end_idx and entries[snap_idx].end_sec - start_sec <= 90:
            end_idx = snap_idx
            end_sec = entries[end_idx].end_sec

        # Skip too-short segments
        if end_sec - start_sec < 20:
            continue

        # Snap to natural SRT boundaries
        bs, be = _find_natural_boundary(entries, start_sec, end_sec)
        seg_entries = entries_in_range(entries, bs, be)
        if len(seg_entries) < 2:
            continue

        segments.append({
            "start_sec": bs,
            "end_sec": be,
            "text": entries_text(seg_entries),
            "section": section,
        })

    return segments


def analyze_srt(
    srt_path: Path,
    word_timestamps: list[dict] | None = None,
    min_duration: float = 20.0,
    max_duration: float = 90.0,
    top_n: int = 15,
) -> list[ClipSuggestion]:
    entries = parse_srt(srt_path)
    if not entries:
        return []
    total_dur = entries[-1].end_sec - entries[0].start_sec

    text_path = srt_path.parent / "text.txt"
    if text_path.exists():
        raw = text_path.read_text(encoding="utf-8")
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", raw.strip())
            if len(p.strip().split()) >= 15
        ]
        segments = _build_segments(paragraphs, entries, total_dur)
    else:
        segments = []

    scored = []
    sign_scored = []
    for seg in segments:
        s, e = seg["start_sec"], seg["end_sec"]
        d = e - s
        if d < min_duration or d > max_duration:
            continue
        pos = s / total_dur if total_dur > 0 else 0
        score = _score_text(seg["text"], pos)

        parts = []
        tl = seg["text"].lower()
        if any(re.search(p, tl) for p in _HOOK_PHRASES): parts.append("hook")
        if any(re.search(p, tl) for p in _KEYWORDS): parts.append("tema-clave")
        if any(re.search(p, tl) for p in _POWER_PHRASES): parts.append("frase-poderosa")
        if pos < 0.12: parts.append("intro")
        if seg.get("section"): parts.append(seg["section"])
        reason = ", ".join(parts) if parts else "interes-general"

        item = (s, e, score, reason, seg["text"])
        if seg.get("section") and seg["section"] not in ("intro",):
            sign_scored.append(item)
        else:
            scored.append(item)

    scored.sort(key=lambda x: x[2], reverse=True)
    sign_scored.sort(key=lambda x: x[2], reverse=True)

    # Prioritize: all sign segments first, then fill with generic
    ordered = sign_scored + scored

    used = []
    suggestions = []
    for s, e, sc, r, t in ordered:
        # Skip if overlaps any existing segment by >50%
        if any(
            max(0, min(e, ue) - max(s, us)) / max(1, max(e - s, ue - us)) > 0.5
            for us, ue in used
        ):
            continue
        segs = entries_in_range(entries, s, e)
        if len(segs) < 2:
            continue
        suggestions.append(ClipSuggestion(start_sec=s, end_sec=e, score=sc, reason=r, text_preview=t, srt_entries=segs))
        used.append((s, e))
        if len(suggestions) >= top_n:
            break
    return suggestions


def analyze_folder(folder: Path, min_duration=20.0, max_duration=90.0, top_n=15) -> list[ClipSuggestion]:
    # Search in root first, then audio/ subdirectory
    srt_files = list(folder.glob("*.srt"))
    if not srt_files:
        audio_dir = folder / "audio"
        if audio_dir.is_dir():
            srt_files = list(audio_dir.glob("*.srt"))
    script_files = [f for f in srt_files if f.name.lower() == "script.srt"]
    sp = script_files[0] if script_files else (srt_files[0] if srt_files else None)
    if sp is None:
        return []
    return analyze_srt(sp, _load_word_timestamps(folder), min_duration, max_duration, top_n)


def find_video_in_folder(folder: Path) -> Path | None:
    """Find the main video file in a project folder.
    
    Checks (in order):
    1. render/output.mp4 (new workflow projects)
    2. render/*.mp4
    3. video.mp4 in root (old projects)
    4. Any .mp4 in root (excluding shorts/)
    """
    # 1. render/output.mp4 (new workflow format)
    render_out = folder / "render" / "output.mp4"
    if render_out.exists():
        return render_out
    # 2. Any video in render/ or videos/ subdirs
    for sub in ["render", "videos"]:
        subdir = folder / sub
        if subdir.is_dir():
            for v in subdir.glob("*.mp4"):
                return v
    # 3. Root video.mp4
    root_video = folder / "video.mp4"
    if root_video.exists():
        return root_video
    # 4. Any root .mp4 (excluding shorts/ which would have 'shorts' in path)
    for ext in (".mp4", ".mov", ".mkv", ".webm"):
        for v in folder.glob(f"*{ext}"):
            if "shorts" not in v.name.lower():
                return v
    return None
