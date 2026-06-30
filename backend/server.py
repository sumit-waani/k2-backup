"""Kaptaan FastAPI server."""
import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from agent import run_agent
from auth import (
    COOKIE_NAME,
    current_user,
    login_user,
    logout_user,
    seed_bootstrap_user,
    update_credentials,
)
from db import (
    execute,
    fetch_all,
    get_configs,
    init_db,
    update_configs,
    create_run,
    finish_run,
    get_run,
    get_active_run,
    append_run_event,
    get_run_events,
    wait_run_event,
)
from sandbox import (
    create_sandbox,
    delete_sandbox,
    get_sandbox,
    SandboxNotConfigured,
    SandboxCreateError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("kaptaan")

app = FastAPI(title="Kaptaan")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)

_bg_tasks: set[asyncio.Task] = set()

# ---------- background agent runner ----------

async def _run_agent_bg(run_id: str, content: str, source: str = "user") -> None:
    """Run agent in background."""
    seq = 0
    status = "done"
    try:
        async for chunk in run_agent(content):
            for line in chunk.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    event_json = line[5:].strip()
                    if event_json:
                        await append_run_event(run_id, seq, event_json)
                        seq += 1
    except Exception:
        logger.exception("background agent run %s failed", run_id)
        status = "error"
    finally:
        await finish_run(run_id, status)
        logger.info("run %s finished status=%s events=%d (source=%s)", run_id, status, seq, source)

def _fire(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

# ---------- startup ----------

@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    await seed_bootstrap_user()

# ---------- schemas ----------

class LoginIn(BaseModel):
    username: str
    password: str

class MessageIn(BaseModel):
    content: str

_MASK_FIELDS = {"llm1_api_key", "firecrawl_key", "daytona_api_key", "vps_password", "vps_ssh_key", "github_pat"}

class SettingsIn(BaseModel):
    llm1_url: str | None = None
    llm1_api_key: str | None = None
    llm1_model: str | None = None
    firecrawl_key: str | None = None
    daytona_api_key: str | None = None
    system_prompt: str | None = None
    memory: str | None = None
    vps_host: str | None = None
    vps_port: str | None = None
    vps_username: str | None = None
    vps_password: str | None = None
    vps_ssh_key: str | None = None
    github_repo_url: str | None = None
    github_pat: str | None = None
    scratchpad: str | None = None
    sandbox_cpu: int | None = None
    sandbox_memory: int | None = None
    sandbox_disk: int | None = None

class CredsIn(BaseModel):
    username: str | None = None
    password: str | None = None

def _mask(cfg: dict) -> dict:
    out = dict(cfg)
    for k in _MASK_FIELDS:
        v = out.get(k) or ""
        out[k] = ("•" * 8) if v else ""
    return out

# ---------- routes ----------

@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}

@app.post("/api/login")
async def login(body: LoginIn, response: Response) -> dict:
    user = await login_user(body.username, body.password, response)
    return {"user": user}

@app.post("/api/logout")
async def logout(
    response: Response,
    kaptaan_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    await logout_user(kaptaan_session or "", response)
    return {"ok": True}

@app.get("/api/me")
async def me(user=Depends(current_user)) -> dict:
    return {"user": user}

@app.get("/api/messages")
async def list_messages(user=Depends(current_user)) -> dict:
    rows = await fetch_all(
        "SELECT id, role, content, created_at FROM messages ORDER BY created_at ASC"
    )
    out = []
    for r in rows:
        if r["role"] in ("user", "assistant"):
            out.append(r)
    return {"messages": out}

@app.delete("/api/messages")
async def clear_messages(user=Depends(current_user)) -> dict:
    await execute("DELETE FROM messages")
    await execute("DELETE FROM run_events")
    await execute("DELETE FROM runs")
    return {"ok": True}

@app.post("/api/message")
async def send_message(body: MessageIn, user=Depends(current_user)) -> dict:
    run_id = await create_run()
    _fire(_run_agent_bg(run_id, body.content, source="user"))
    return {"run_id": run_id}

@app.get("/api/run/{run_id}/stream")
async def stream_run(
    run_id: str,
    after: int = Query(default=-1),
    user=Depends(current_user),
) -> StreamingResponse:
    async def gen():
        seq = after
        while True:
            rows = await get_run_events(run_id, after_seq=seq)
            for row in rows:
                payload = json.dumps({"seq": row["seq"], "event": json.loads(row["event_json"])})
                yield f"data: {payload}\n\n"
                seq = row["seq"]

            run = await get_run(run_id)
            if not run or run["status"] != "running":
                rows = await get_run_events(run_id, after_seq=seq)
                for row in rows:
                    payload = json.dumps({"seq": row["seq"], "event": json.loads(row["event_json"])})
                    yield f"data: {payload}\n\n"
                break

            await wait_run_event(run_id, timeout=2.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

@app.get("/api/runs/active")
async def active_run(user=Depends(current_user)) -> dict:
    run = await get_active_run()
    return {"run": run}

@app.get("/api/settings")
async def get_settings(user=Depends(current_user)) -> dict:
    cfg = await get_configs()
    return {"settings": _mask(cfg), "user": user}

@app.post("/api/settings")
async def post_settings(body: SettingsIn, user=Depends(current_user)) -> dict:
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    for k in _MASK_FIELDS:
        if k in updates and updates[k] and set(updates[k]) <= {"•"}:
            updates.pop(k)
    if updates:
        await update_configs(**updates)
    cfg = await get_configs()
    return {"settings": _mask(cfg)}

@app.post("/api/vps/test")
async def vps_test(user=Depends(current_user)) -> dict:
    """Test VPS SSH connection using saved credentials."""
    import paramiko, io as _io
    cfg = await get_configs()
    host = cfg.get("vps_host", "")
    if not host:
        raise HTTPException(400, "VPS host not configured")

    port = int(cfg.get("vps_port") or 22)
    username = cfg.get("vps_username") or "root"
    password = cfg.get("vps_password") or ""
    key_data = cfg.get("vps_ssh_key") or ""

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        kwargs = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": 10,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_data:
            pkey = None
            for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
                try:
                    pkey = cls.from_private_key(_io.StringIO(key_data))
                    break
                except Exception:
                    continue
            if pkey is None:
                raise HTTPException(400, "Could not parse SSH private key")
            kwargs["pkey"] = pkey
        elif password:
            kwargs["password"] = password
        else:
            raise HTTPException(400, "No password or SSH key configured")

        client.connect(**kwargs)
        _, stdout, _ = client.exec_command("echo ok", timeout=10)
        result = stdout.read().decode().strip()
        if result == "ok":
            return {"ok": True, "message": f"Connected to {username}@{host}:{port}"}
        return {"ok": False, "message": "Unexpected response from server"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
    finally:
        client.close()

@app.post("/api/credentials")
async def post_credentials(body: CredsIn, user=Depends(current_user)) -> dict:
    await update_credentials(user["id"], body.username, body.password)
    return {"ok": True}

@app.post("/api/sandbox/reset")
async def sandbox_reset(user=Depends(current_user)) -> dict:
    cfg = await get_configs()
    if not (cfg.get("github_repo_url") or "").strip():
        raise HTTPException(400, "GitHub repo URL required. Add it in Settings → GitHub first.")
    if not (cfg.get("github_pat") or "").strip():
        raise HTTPException(400, "GitHub PAT required. Add it in Settings → GitHub first.")
    try:
        old = await get_sandbox()
        if old:
            await delete_sandbox()
        sid = await create_sandbox()
        return {"sandbox_id": sid}
    except SandboxNotConfigured:
        raise HTTPException(400, "Daytona API key not configured")
    except SandboxCreateError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.exception("Unexpected error during sandbox reset")
        raise HTTPException(500, f"Sandbox reset failed: {e}")

@app.post("/api/sandbox/create")
async def sandbox_create(user=Depends(current_user)) -> dict:
    cfg = await get_configs()
    if not (cfg.get("github_repo_url") or "").strip():
        raise HTTPException(400, "GitHub repo URL required. Add it in Settings → GitHub first.")
    if not (cfg.get("github_pat") or "").strip():
        raise HTTPException(400, "GitHub PAT required. Add it in Settings → GitHub first.")
    try:
        sid = await create_sandbox()
        return {"sandbox_id": sid}
    except SandboxNotConfigured:
        raise HTTPException(400, "Daytona API key not configured")
    except SandboxCreateError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.exception("Unexpected error during sandbox creation")
        raise HTTPException(500, f"Sandbox creation failed: {e}")

@app.get("/api/sandbox")
async def sandbox_info(user=Depends(current_user)) -> dict:
    try:
        sb = await get_sandbox()
        state = getattr(sb, "state", "unknown")
        state_val = state.value if hasattr(state, "value") else str(state)
        return {
            "id": sb.id,
            "state": state_val,
        }
    except SandboxNotConfigured as e:
        raise HTTPException(400, str(e))

@app.post("/api/sandbox/delete")
async def sandbox_delete(user=Depends(current_user)) -> dict:
    result = await delete_sandbox()
    return result
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
