import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.core.job_store import get_db
from app.models.channel import ChannelCreate, ChannelMetadata, make_channel_id
from app.models.fragment import Fragment
from app.models.project import ProjectMetadata, ProjectFiles, ProjectStats


# ── Channels ─────────────────────────────────────────────

async def list_channels() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, base_path, created_at, updated_at FROM channels ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def create_channel(body: ChannelCreate) -> ChannelMetadata:
    now = datetime.now(timezone.utc).isoformat()
    cid = make_channel_id(body.name)
    parent_path = Path(body.base_path).resolve()
    path = parent_path / cid
    path.mkdir(parents=True, exist_ok=True)

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO channels (id, name, base_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (cid, body.name, str(path), now, now),
        )
        await db.commit()
    finally:
        await db.close()

    return ChannelMetadata(id=cid, name=body.name, base_path=str(path), created_at=now, updated_at=now)


async def delete_channel(cid: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM channels WHERE id = ?", (cid,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def setup_status() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM channels")
        row = await cursor.fetchone()
        suggested = ""
        candidates = [
            Path.home() / "Documents" / "Youtube",
            Path.home() / "Documents",
            Path.cwd(),
        ]
        for c in candidates:
            if c.exists():
                suggested = str(c)
                break
        return {"has_channels": row["cnt"] > 0, "suggested_base": suggested}
    finally:
        await db.close()


# ── Projects ─────────────────────────────────────────────

async def list_projects(channel_id: str | None = None) -> list[dict]:
    db = await get_db()
    try:
        if channel_id:
            cursor = await db.execute(
                "SELECT id, name, path, created_at, updated_at, status, channel_id FROM projects WHERE channel_id = ? ORDER BY updated_at DESC",
                (channel_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT id, name, path, created_at, updated_at, status, channel_id FROM projects ORDER BY updated_at DESC"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def create_project(name: str, title: str = "", channel_id: str = "default") -> ProjectMetadata:
    now = datetime.now(timezone.utc).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute("SELECT base_path FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Channel '{channel_id}' not found")
        base_path = row["base_path"]
    finally:
        await db.close()

    folder = Path(base_path) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio").mkdir(exist_ok=True)
    (folder / "imagenes").mkdir(exist_ok=True)

    meta = ProjectMetadata(
        name=name,
        title=title or name,
        created=now,
        status="editing",
        base_dir=str(folder),
        files=ProjectFiles(),
        stats=ProjectStats(),
        history=[],
    )

    pj = folder / "project.json"
    pj.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO projects (id, name, channel_id, path, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, name, channel_id, str(folder), now, now, "active"),
        )
        await db.commit()
    finally:
        await db.close()

    return meta


async def get_project(name: str) -> ProjectMetadata | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            return None
        path = row["path"]
    finally:
        await db.close()

    pj = Path(path) / "project.json"
    if not pj.exists():
        return None
    data = json.loads(pj.read_text(encoding="utf-8"))
    meta = ProjectMetadata(**data)

    pp = _resolve_prompts_path(path)
    if pp and pp.exists():
        fragments = json.loads(pp.read_text(encoding="utf-8"))
        meta.stats.prompts_total = len(fragments)

    # Sync images_generated with actual files on disk
    img_dir = Path(path) / "imagenes"
    generated = 0
    if img_dir.exists():
        generated = len(list(img_dir.glob("escena_*.png")))
    meta.stats.images_generated = generated
    meta.stats.images_failed = max(0, meta.stats.prompts_total - generated)

    return meta


async def save_project_style(project_id: str, style: str) -> None:
    """Persist the prompt style in project.json."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            return
        path = row["path"]
    finally:
        await db.close()

    pj = Path(path) / "project.json"
    if not pj.exists():
        return
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["prompt_style"] = style
    pj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def update_project_meta(project_id: str, updates: dict) -> None:
    """Update arbitrary fields in project.json (merge)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            return
        path = row["path"]
    finally:
        await db.close()

    pj = Path(path) / "project.json"
    if not pj.exists():
        return
    data = json.loads(pj.read_text(encoding="utf-8"))
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    pj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def delete_project(name: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM projects WHERE id = ?", (name,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ── Orphaned Project Scanner ──────────────────────────────

async def scan_orphaned_projects() -> list[dict]:
    """Scan channel directories for project folders not in the DB."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, name, base_path FROM channels")
        channels = await cursor.fetchall()
        cursor2 = await db.execute("SELECT id FROM projects")
        db_ids = set(r["id"] for r in await cursor2.fetchall())
    finally:
        await db.close()

    orphans = []
    for ch in channels:
        base = Path(ch["base_path"])
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            if not folder.is_dir() or folder.name.startswith("_") or folder.name.startswith("."):
                continue
            if folder.name in db_ids:
                continue
            pj = folder / "project.json"
            if not pj.exists():
                continue
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
                title = data.get("title", data.get("name", folder.name))
                created = data.get("created", "")
                has_video = any(
                    folder.glob("*.mp4")
                ) or any(
                    (folder / d).glob("*.mp4") for d in ("render", "videos", "output") if (folder / d).is_dir()
                )
                has_audio = any(folder.glob("*.mp3")) or any(folder.glob("*.m4a")) or any(folder.glob("*.wav"))
                has_images = (folder / "imagenes").is_dir() and len(list((folder / "imagenes").glob("*.png"))) > 0
                orphans.append({
                    "id": folder.name,
                    "title": title,
                    "channel_id": ch["id"],
                    "channel_name": ch["name"],
                    "path": str(folder),
                    "created": created,
                    "has_video": has_video,
                    "has_audio": has_audio,
                    "has_images": has_images,
                })
            except (json.JSONDecodeError, KeyError):
                continue
    return orphans


async def import_orphaned_project(project_id: str, channel_id: str) -> bool:
    """Register an orphaned project folder in the DB."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT base_path FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Channel '{channel_id}' not found")
    finally:
        await db.close()

    folder = Path(row["base_path"]) / project_id
    if not folder.is_dir():
        raise ValueError(f"Folder not found: {folder}")

    pj = folder / "project.json"
    if not pj.exists():
        raise ValueError(f"project.json not found in {folder}")

    data = json.loads(pj.read_text(encoding="utf-8"))
    title = data.get("title", data.get("name", project_id))
    created = data.get("created", datetime.now(timezone.utc).isoformat())
    now = datetime.now(timezone.utc).isoformat()

    # Fix base_dir in project.json to match actual folder location
    actual_path = str(folder)
    if data.get("base_dir") != actual_path:
        data["base_dir"] = actual_path

    # Normalize legacy project structure:
    # - Ensure audio/ subdirectory exists with audio + transcription files
    # - Ensure imagenes/ subdirectory exists
    audio_dir = folder / "audio"
    if not audio_dir.exists():
        audio_dir.mkdir(exist_ok=True)
        # Move audio files from root to audio/
        for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
            for f in folder.glob(f"*{ext}"):
                f.rename(audio_dir / f.name)
        # Move transcription files from root to audio/
        for name in ("script.json", "script.srt", "text.txt", "reference.txt"):
            src = folder / name
            if src.exists():
                src.rename(audio_dir / src.name)
        # Update files paths in project.json
        data.setdefault("files", {})
        if not data["files"].get("audio"):
            for ext in (".mp3", ".wav", ".m4a"):
                found = list(audio_dir.glob(f"*{ext}"))
                if found:
                    data["files"]["audio"] = found[0].name

    imagenes_dir = folder / "imagenes"
    if not imagenes_dir.exists():
        imagenes_dir.mkdir(exist_ok=True)

    # Write updated project.json
    pj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO projects (id, name, channel_id, path, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, title, channel_id, str(folder), created, now, "active"),
        )
        await db.commit()
    finally:
        await db.close()
    return True


# ── Fragments ────────────────────────────────────────────

async def list_fragments(name: str) -> list[Fragment]:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            return []
        project_dir = row["path"]
    finally:
        await db.close()

    pp = _resolve_prompts_path(project_dir)
    if not pp:
        return []
    data = json.loads(pp.read_text(encoding="utf-8"))
    # Null-safe: fill null provider/model with empty string (legacy projects)
    for f in data:
        if f.get("provider") is None:
            f["provider"] = ""
        if f.get("model") is None:
            f["model"] = ""
    return [Fragment(**f) for f in data]


async def update_fragment(name: str, fragment_id: int, data: dict) -> Fragment | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            return None
        project_dir = row["path"]
    finally:
        await db.close()

    pp = _resolve_prompts_path(project_dir)
    if not pp:
        return None

    fragments = json.loads(pp.read_text(encoding="utf-8"))
    for f in fragments:
        if f["fragment_id"] == fragment_id:
            f.update(data)
            f["updatedAt"] = datetime.now(timezone.utc).isoformat()
            pp.write_text(json.dumps(fragments, ensure_ascii=False, indent=2), encoding="utf-8")
            return Fragment(**f)

    return None


# ── Script Text (full guion) ──────────────────────────────


def fragmentar_estricto_21(texto: str, min_p: int = 15, max_p: int = 21) -> list[str]:
    """Split text into fragments of 15-21 words, cutting at punctuation when possible."""
    import re as _re
    texto = _re.sub(r'\s+', ' ', texto).strip()
    palabras = texto.split()
    fragmentos: list[str] = []
    inicio = 0

    while inicio < len(palabras):
        if len(palabras) - inicio <= max_p:
            fragmentos.append(" ".join(palabras[inicio:]))
            break

        ventana_inicio = inicio + min_p
        ventana_fin = min(inicio + max_p, len(palabras))
        sub_texto_ventana = " ".join(palabras[ventana_inicio:ventana_fin])
        matches = list(_re.finditer(r'[.,;:]', sub_texto_ventana))

        if matches:
            ultimo_signo = matches[-1]
            palabras_hasta_signo = sub_texto_ventana[:ultimo_signo.end()].split()
            corte_final = ventana_inicio + len(palabras_hasta_signo)
            if corte_final > inicio + max_p:
                corte_final = inicio + max_p
            segmento = palabras[inicio:corte_final]
        else:
            segmento = palabras[inicio:inicio + max_p]

        fragmentos.append(" ".join(segmento))
        inicio += len(segmento)

    return fragmentos


async def create_script_fragments(project_id: str, text: str | None = None) -> list[Fragment]:
    """Run strict-21 fragmentation on the script text and save fragments to prompts-*.json."""
    from datetime import datetime, timezone
    import json

    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError("Project not found")
        project_dir = row["path"]
    finally:
        await db.close()

    project_path = Path(project_dir)

    # Read text from text.txt if not provided
    if text is None:
        text = await get_script(project_id)
        if text is None:
            raise ValueError("No script text found. Add the full script first.")

    # Run fragmentation
    raw_fragments = fragmentar_estricto_21(text)

    # Determine next fragment_id
    existing = list_fragments_sync(project_path)
    next_id = max((f.fragment_id for f in existing), default=0) + 1

    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompts_path = project_path / f"prompts-{today}.json"

    # Load existing or create new
    if prompts_path.exists():
        all_fragments = json.loads(prompts_path.read_text(encoding="utf-8"))
    else:
        all_fragments = []

    for i, segment in enumerate(raw_fragments):
        all_fragments.append({
            "fragment_id": next_id + i,
            "original_text": segment,
            "image_prompt": "",
            "source": "manual",
            "status": "pending",
            "provider": "",
            "model": "",
            "updatedAt": now,
        })

    prompts_path.write_text(
        json.dumps(all_fragments, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return [Fragment(**f) for f in all_fragments]


def list_fragments_sync(project_path: Path) -> list[Fragment]:
    """Synchronous helper to list fragments without DB."""
    pp = _resolve_prompts_path(str(project_path))
    if not pp or not pp.exists():
        return []
    data = json.loads(pp.read_text(encoding="utf-8"))
    for f in data:
        if f.get("provider") is None:
            f["provider"] = ""
        if f.get("model") is None:
            f["model"] = ""
    return [Fragment(**f) for f in data]


async def get_script(project_id: str) -> str | None:
    """Read the full script text from audio/text.txt."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        project_dir = row["path"]
    finally:
        await db.close()

    # Try audio/text.txt first, then root text.txt as fallback
    for candidate in (
        Path(project_dir) / "audio" / "text.txt",
        Path(project_dir) / "text.txt",
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return None


async def save_script(project_id: str, text: str) -> str:
    """Save the full script text to audio/text.txt."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError("Project not found")
        project_dir = row["path"]
    finally:
        await db.close()

    audio_dir = Path(project_dir) / "audio"
    audio_dir.mkdir(exist_ok=True)

    target = audio_dir / "text.txt"
    target.write_text(text, encoding="utf-8")
    return str(target)


def _resolve_prompts_path(project_dir: str) -> Path | None:
    p = Path(project_dir)
    files = list(p.glob("prompts-*.json"))
    if files:
        return files[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidate = p / f"prompts-{today}.json"
    return candidate if candidate.exists() else None
