from __future__ import annotations

import sys
from pathlib import Path

import typer

from app.services.shorts_maker.analyzer import analyze_folder, find_video_in_folder
from app.services.shorts_maker.clipper import render_job
from app.services.shorts_maker.types import RenderJob

app = typer.Typer(
    name="shorts-maker",
    help="Creador de YouTube Shorts a partir de videos con guion y subtitulos",
)


@app.command()
def analyze(
    folder: str = typer.Argument(..., help="Carpeta del proyecto (contiene video + SRT)"),
    min_duration: float = typer.Option(15.0, help="Duracion minima del short (segundos)"),
    max_duration: float = typer.Option(90.0, help="Duracion maxima del short (segundos)"),
    top: int = typer.Option(10, help="Cantidad de sugerencias a mostrar"),
):
    """Analiza un proyecto y sugiere los mejores momentos para shorts."""
    project = Path(folder)
    if not project.exists():
        typer.echo(f"Error: carpeta '{folder}' no existe", err=True)
        raise typer.Exit(1)

    suggestions = analyze_folder(project, min_duration, max_duration, top)

    if not suggestions:
        typer.echo("No se encontraron momentos candidatos para shorts.")
        return

    typer.echo(f"\n{'='*80}")
    typer.echo(f"  Top {len(suggestions)} momentos para Shorts")
    typer.echo(f"{'='*80}\n")

    video_path = find_video_in_folder(project)
    if video_path:
        typer.echo(f"  Video: {video_path.name}")
    typer.echo()

    for i, s in enumerate(suggestions, 1):
        minutes_s = int(s.start_sec // 60)
        seconds_s = int(s.start_sec % 60)
        minutes_e = int(s.end_sec // 60)
        seconds_e = int(s.end_sec % 60)

        typer.echo(f"  #{i}  [{minutes_s:02d}:{seconds_s:02d} -> {minutes_e:02d}:{seconds_e:02d}]")
        typer.echo(f"      Duracion: {s.duration:.0f}s  |  Score: {s.score:.1f}  |  {s.reason}")
        typer.echo(f"      {s.text_preview[:120]}...")
        typer.echo()

    typer.echo(f"{'='*80}")
    typer.echo(f"  Usa: shorts-maker render <carpeta> --select <numero>")
    typer.echo(f"{'='*80}\n")


@app.command()
def render(
    folder: str = typer.Argument(..., help="Carpeta del proyecto"),
    select: str = typer.Option(
        "all",
        help="Numero(s) de sugerencia a renderizar (ej: 1, 1-3, o 'all')",
    ),
    output: str = typer.Option("output", help="Directorio de salida"),
    font_size: int = typer.Option(52, help="Tamano de fuente para subtitulos"),
    with_subtitles: bool = typer.Option(True, help="Quemar subtitulos en el video"),
):
    """Renderiza los shorts seleccionados."""
    project = Path(folder)
    if not project.exists():
        typer.echo(f"Error: carpeta '{folder}' no existe", err=True)
        raise typer.Exit(1)

    video_path = find_video_in_folder(project)
    if not video_path:
        typer.echo("Error: no se encontro video en la carpeta", err=True)
        raise typer.Exit(1)

    srt_files = list(project.glob("*.srt"))
    srt_path = srt_files[0] if srt_files else None

    suggestions = analyze_folder(project, top_n=20)

    if not suggestions:
        typer.echo("No se encontraron momentos para renderizar.")
        return

    indices = _parse_selection(select, len(suggestions))
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    project_name = project.name

    for idx in indices:
        s = suggestions[idx - 1]
        out_name = f"{project_name}_short_{idx:02d}.mp4"
        out_path = output_dir / out_name

        typer.echo(f"Renderizando short #{idx} -> {out_name}...")

        job = RenderJob(
            suggestion=s,
            video_path=video_path,
            srt_path=srt_path if with_subtitles else None,
            output_path=out_path,
            font_size=font_size,
        )

        try:
            result = render_job(job)
            typer.echo(f"  [OK] {result}")
        except Exception as e:
            typer.echo(f"  [ERROR] {e}", err=True)

    typer.echo(f"\nListo. Shorts en: {output_dir.absolute()}")


@app.command()
def info(
    folder: str = typer.Argument(..., help="Carpeta del proyecto"),
):
    """Muestra informacion del proyecto."""
    project = Path(folder)
    if not project.exists():
        typer.echo(f"Error: carpeta '{folder}' no existe", err=True)
        raise typer.Exit(1)

    video_path = find_video_in_folder(project)
    srt_files = list(project.glob("*.srt"))
    prompt_files = list(project.glob("prompts-*.json"))

    typer.echo(f"\n  Proyecto: {project.name}")
    typer.echo(f"  Video:    {video_path.name if video_path else 'NO ENCONTRADO'}")
    typer.echo(f"  SRT:      {srt_files[0].name if srt_files else 'NO ENCONTRADO'}")
    typer.echo(f"  Prompts:  {prompt_files[0].name if prompt_files else 'NO ENCONTRADO'}")

    if video_path:
        from app.services.shorts_maker.clipper import get_video_info
        try:
            info = get_video_info(video_path)
            fmt = info.get("format", {})
            duration_s = float(fmt.get("duration", 0))
            minutes = int(duration_s // 60)
            seconds = int(duration_s % 60)
            typer.echo(f"  Duracion: {minutes}:{seconds:02d}")

            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    w = stream.get("width", "?")
                    h = stream.get("height", "?")
                    typer.echo(f"  Resolucion: {w}x{h}")
                    break
        except Exception:
            pass

    typer.echo()


def _parse_selection(select: str, max_n: int) -> list[int]:
    if select.lower() == "all":
        return list(range(1, max_n + 1))

    indices: list[int] = []
    for part in select.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            indices.extend(range(int(a), int(b) + 1))
        else:
            indices.append(int(part))

    return sorted(set(i for i in indices if 1 <= i <= max_n))


def main():
    app()


if __name__ == "__main__":
    main()
