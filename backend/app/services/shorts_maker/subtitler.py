from __future__ import annotations

from pathlib import Path

from app.services.shorts_maker.srt_parser import SrtEntry, parse_srt


def _srt_to_srt_content(entries: list[SrtEntry]) -> str:
    lines: list[str] = []
    for i, entry in enumerate(entries, 1):
        start = _format_srt_time(entry.start_sec)
        end = _format_srt_time(entry.end_sec)
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(entry.text)
        lines.append("")
    return "\n".join(lines)


def _format_srt_time(total_seconds: float) -> str:
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    millis = int((total_seconds - int(total_seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def extract_srt_segment(
    srt_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
) -> None:
    entries = parse_srt(srt_path)
    segment_entries = [
        e for e in entries
        if e.end_sec > start_sec and e.start_sec < end_sec
    ]

    shifted: list[SrtEntry] = []
    for entry in segment_entries:
        new_start = max(0, entry.start_sec - start_sec)
        new_end = entry.end_sec - start_sec
        shifted.append(
            SrtEntry(
                index=entry.index,
                start_sec=new_start,
                end_sec=new_end,
                text=entry.text,
            )
        )

    content = _srt_to_srt_content(shifted)
    output_path.write_text(content, encoding="utf-8")


def create_subtitle_ass(
    srt_path: Path,
    ass_path: Path,
    video_width: int = 1080,
    video_height: int = 1920,
    font_ratio: float = 0.028,
    outline_ratio: float = 0.004,
    shadow_ratio: float = 0.002,
) -> None:
    entries = parse_srt(srt_path)

    font_size = int(video_height * font_ratio)
    outline = outline_ratio * video_height
    shadow = shadow_ratio * video_height
    margin_v = int(video_height * 0.16)
    margin_lr = int(video_width * 0.04)

    header = [
        "[Script Info]",
        f"PlayResX: {video_width}",
        f"PlayResY: {video_height}",
        "ScaledBorderAndShadow: no",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            f"Style: Text,Arial,{font_size},&H00FFFFFF,&H000000FF,"
            f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,"
            f"{outline:.1f},{shadow:.1f},2,"
            f"{margin_lr},{margin_lr},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text",
    ]

    for entry in entries:
        start = _ass_time(entry.start_sec)
        end = _ass_time(entry.end_sec)
        text = entry.text.replace("\n", "\\N")
        header.append(
            f"Dialogue: 0,{start},{end},Text,,0,0,0,,{text}"
        )

    ass_path.write_text("\n".join(header), encoding="utf-8")


def _ass_time(total_seconds: float) -> str:
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    centiseconds = int((total_seconds - int(total_seconds)) * 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
