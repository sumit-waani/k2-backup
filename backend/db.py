"""SQLite (aiosqlite) database for Kaptaan."""
import asyncio
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Any

import aiosqlite

DB_PATH = os.environ.get("KAPTAAN_DB_PATH", "/app/backend/kaptaan.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    session_token TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configs (
    id TEXT PRIMARY KEY,
    llm1_url TEXT DEFAULT '',
    llm1_api_key TEXT DEFAULT '',
    llm1_model TEXT DEFAULT 'deepseek-v4-pro',
    llm2_url TEXT DEFAULT '',
    llm2_api_key TEXT DEFAULT '',
    llm2_model TEXT DEFAULT '',
    active_llm TEXT DEFAULT 'llm1',
    firecrawl_key TEXT DEFAULT '',
    daytona_api_key TEXT DEFAULT '',
    sandbox_id TEXT DEFAULT '',
    sandbox_cpu INTEGER DEFAULT 4,
    sandbox_memory INTEGER DEFAULT 8,
    sandbox_disk INTEGER DEFAULT 10,
    memory TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    vps_host TEXT DEFAULT '',
    vps_port TEXT DEFAULT '22',
    vps_username TEXT DEFAULT '',
    vps_password TEXT DEFAULT '',
    vps_ssh_key TEXT DEFAULT '',
    vps2_host TEXT DEFAULT '',
    vps2_port TEXT DEFAULT '22',
    vps2_username TEXT DEFAULT '',
    vps2_password TEXT DEFAULT '',
    vps2_ssh_key TEXT DEFAULT '',
    github_repo_url TEXT DEFAULT '',
    github_pat TEXT DEFAULT '',
    scratchpad TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_users_session ON users(session_token);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_events ON run_events(run_id, seq);

"""

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def new_id() -> str:
    return str(uuid.uuid4())

# ---- In-memory event notification (replaces DB polling) ----

_event_watchers: dict[str, set[asyncio.Event]] = defaultdict(set)

def _notify_run_event(run_id: str) -> None:
    """Wake up all subscribers waiting for events on this run."""
    for evt in _event_watchers.get(run_id, set()):
        evt.set()

def watch_run(run_id: str) -> asyncio.Event:
    """Create and register an Event for a stream subscriber."""
    evt = asyncio.Event()
    _event_watchers[run_id].add(evt)
    return evt

def unwatch_run(run_id: str, evt: asyncio.Event) -> None:
    """Remove a subscriber's Event."""
    watchers = _event_watchers.get(run_id)
    if watchers:
        watchers.discard(evt)
        if not watchers:
            _event_watchers.pop(run_id, None)

async def wait_run_event(run_id: str, timeout: float = 2.0) -> bool:
    """Wait for a new event notification. Returns True if notified, False on timeout."""
    evt = watch_run(run_id)
    try:
        return await asyncio.wait_for(evt.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    finally:
        unwatch_run(run_id, evt)

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        # Ensure single configs row exists
        cur = await db.execute("SELECT id FROM configs LIMIT 1")
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO configs (id) VALUES (?)",
                (new_id(),),
            )
        # ---- lightweight migrations (idempotent) ----
        cur = await db.execute("PRAGMA table_info(configs)")
        cols = {r[1] for r in await cur.fetchall()}
        if "daytona_api_key" not in cols:
            await db.execute(
                "ALTER TABLE configs ADD COLUMN daytona_api_key TEXT DEFAULT ''"
            )
        for vps_col in ("vps_host", "vps_port", "vps_username", "vps_password", "vps_ssh_key"):
            if vps_col not in cols:
                await db.execute(
                    f"ALTER TABLE configs ADD COLUMN {vps_col} TEXT DEFAULT ''"
                )
        for vps2_col in ("vps2_host", "vps2_port", "vps2_username", "vps2_password", "vps2_ssh_key"):
            if vps2_col not in cols:
                default = "'22'" if vps2_col == "vps2_port" else "''"
                await db.execute(
                    f"ALTER TABLE configs ADD COLUMN {vps2_col} TEXT DEFAULT {default}"
                )
        for git_col in ("github_repo_url", "github_pat", "scratchpad"):
            if git_col not in cols:
                await db.execute(
                    f"ALTER TABLE configs ADD COLUMN {git_col} TEXT DEFAULT ''"
                )
        # Sandbox resource specs (configurable per project)
        if "sandbox_cpu" not in cols:
            await db.execute("ALTER TABLE configs ADD COLUMN sandbox_cpu INTEGER DEFAULT 4")
        if "sandbox_memory" not in cols:
            await db.execute("ALTER TABLE configs ADD COLUMN sandbox_memory INTEGER DEFAULT 8")
        if "sandbox_disk" not in cols:
            await db.execute("ALTER TABLE configs ADD COLUMN sandbox_disk INTEGER DEFAULT 10")
        # One-time bootstrap: copy DAYTONA_API_KEY from env into DB on the very
        # first install so existing deployments keep working. Once stored in
        # DB we never re-read from env.
        cur = await db.execute("SELECT daytona_api_key FROM configs LIMIT 1")
        existing = (await cur.fetchone())[0] or ""
        if not existing:
            env_key = os.environ.get("DAYTONA_API_KEY", "").strip()
            if env_key:
                await db.execute(
                    "UPDATE configs SET daytona_api_key = ?", (env_key,)
                )
        # Mark any runs that were left 'running' from a previous server session
        # as 'abandoned' — they can't be resumed after restart.
        await db.execute(
            "UPDATE runs SET status = 'abandoned', finished_at = ? WHERE status = 'running'",
            (now_iso(),),
        )
        await db.commit()

async def get_db() -> aiosqlite.Connection:
    """Get a fresh connection. Caller must close."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def fetch_one(query: str, params: tuple = ()) -> Optional[dict]:
    db = await get_db()
    try:
        cur = await db.execute(query, params)
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute(query, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()

async def execute(query: str, params: tuple = ()) -> None:
    db = await get_db()
    try:
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()

async def get_configs() -> dict:
    row = await fetch_one("SELECT * FROM configs LIMIT 1")
    return row or {}

async def update_configs(**kwargs: Any) -> None:
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = tuple(kwargs.values())
    await execute(f"UPDATE configs SET {sets}", values)

# ---- runs ----

async def create_run() -> str:
    run_id = new_id()
    await execute(
        "INSERT INTO runs (id, status, created_at) VALUES (?, 'running', ?)",
        (run_id, now_iso()),
    )
    return run_id

async def finish_run(run_id: str, status: str = "done") -> None:
    await execute(
        "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
        (status, now_iso(), run_id),
    )

async def get_run(run_id: str) -> Optional[dict]:
    return await fetch_one("SELECT * FROM runs WHERE id = ?", (run_id,))

async def get_active_run() -> Optional[dict]:
    return await fetch_one(
        "SELECT * FROM runs WHERE status = 'running' ORDER BY created_at DESC LIMIT 1"
    )

async def append_run_event(run_id: str, seq: int, event_json: str) -> None:
    await execute(
        "INSERT INTO run_events (id, run_id, seq, event_json, created_at) VALUES (?,?,?,?,?)",
        (new_id(), run_id, seq, event_json, now_iso()),
    )
    _notify_run_event(run_id)

async def get_run_events(run_id: str, after_seq: int = -1) -> list[dict]:
    return await fetch_all(
        "SELECT seq, event_json FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
        (run_id, after_seq),
    )
