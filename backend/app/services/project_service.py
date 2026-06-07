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


async def delete_project(name: str) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM projects WHERE id = ?", (name,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


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


def _resolve_prompts_path(project_dir: str) -> Path | None:
    p = Path(project_dir)
    files = list(p.glob("prompts-*.json"))
    if files:
        return files[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidate = p / f"prompts-{today}.json"
    return candidate if candidate.exists() else None
