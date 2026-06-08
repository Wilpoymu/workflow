from __future__ import annotations

import re
from pathlib import Path

from app.services.shorts_maker.types import SrtEntry

_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(path: Path) -> list[SrtEntry]:
    raw = path.read_text(encoding="utf-8")
    entries: list[SrtEntry] = []
    blocks = raw.strip().split("\n\n")

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        m = _TIME_RE.match(lines[1].strip())
        if not m:
            continue

        start = _to_seconds(*m.group(1, 2, 3, 4))
        end = _to_seconds(*m.group(5, 6, 7, 8))
        text = " ".join(line.strip() for line in lines[2:])

        entries.append(SrtEntry(index=index, start_sec=start, end_sec=end, text=text))

    return entries


def entries_in_range(
    entries: list[SrtEntry], start: float, end: float
) -> list[SrtEntry]:
    return [e for e in entries if e.start_sec >= start and e.end_sec <= end]


def entries_text(entries: list[SrtEntry]) -> str:
    return " ".join(e.text for e in entries)
