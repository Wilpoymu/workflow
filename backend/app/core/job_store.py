import aiosqlite
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DB_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / ".."
DB_PATH = str(DB_DIR / "workflow.db")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db() -> None:
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel_id TEXT DEFAULT 'default',
                path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS job_queue (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                progress REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT
            )
        """)
        await db.commit()

        await _migrate_v1(db)
        await _migrate_legacy_projects(db)
    finally:
        await db.close()


async def _migrate_v1(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(projects)")
    columns = [row["name"] for row in await cursor.fetchall()]
    if "channel_id" not in columns:
        await db.execute("ALTER TABLE projects ADD COLUMN channel_id TEXT DEFAULT 'default'")
        await db.commit()


async def _migrate_legacy_projects(db: aiosqlite.Connection) -> None:
    legacy_dir = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / ".." / "projects"
    if not legacy_dir.exists():
        return

    projects = [d for d in legacy_dir.iterdir() if d.is_dir() and (d / "project.json").exists()]
    if not projects:
        return

    cursor = await db.execute("SELECT COUNT(*) as cnt FROM channels WHERE id = 'default'")
    row = await cursor.fetchone()
    if row["cnt"] > 0:
        return

    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "INSERT INTO channels (id, name, base_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("default", "Default", str(legacy_dir.resolve()), now, now),
    )

    for p in projects:
        pj = p / "project.json"
        try:
            meta = json.loads(pj.read_text(encoding="utf-8"))
            meta["channel_id"] = "default"
            pj.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        await db.execute(
            "INSERT OR REPLACE INTO projects (id, name, path, created_at, updated_at, status, channel_id) VALUES (?, ?, ?, ?, ?, ?, 'default')",
            (p.name, p.name, str(p), now, now, "active"),
        )

    await db.commit()
