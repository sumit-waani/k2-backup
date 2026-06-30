"""Daytona sandbox manager.

Key + sandbox id live in the SQLite `configs` row, NOT in env vars. The app
runs fine without a Daytona key — `shell_exec` simply returns a clear error
until the user adds a key and clicks "Create sandbox" in Settings.

Native SDK APIs used for git and filesystem operations.
"""
import asyncio
import logging
from typing import Optional

from daytona_sdk import (
    AsyncDaytona,
    DaytonaConfig,
    CreateSandboxFromImageParams,
    Image,
    Resources,
)

from db import get_configs, update_configs

logger = logging.getLogger(__name__)

# Cached client + sandbox; rebuilt whenever the stored key changes.
_client: Optional[AsyncDaytona] = None
_client_key: str = ""

REPO_DIR = "/home/daytona/repo"

# Branches to try when cloning (in order). Empty string means "default branch".
CLONE_BRANCHES = ("main", "master", "")

# Default sandbox specs
DEFAULT_CPU = 4
DEFAULT_MEMORY = 8
DEFAULT_DISK = 10


class SandboxNotConfigured(Exception):
    """Raised when Daytona key or sandbox is missing."""


class SandboxCreateError(Exception):
    """Raised when sandbox creation fails for any reason."""


async def _get_client() -> AsyncDaytona:
    global _client, _client_key
    cfg = await get_configs()
    api_key = (cfg.get("daytona_api_key") or "").strip()
    if not api_key:
        raise SandboxNotConfigured(
            "Daytona API key not set. Open Settings → Daytona to add one."
        )
    if _client is None or _client_key != api_key:
        _client = AsyncDaytona(DaytonaConfig(api_key=api_key))
        _client_key = api_key
    return _client


def _build_image() -> Image:
    """Build a Debian-slim Python image with git + essentials pre-installed.

    NOTE: run_commands() adds the RUN prefix automatically — do NOT
    include RUN in the command strings.
    """
    return (
        Image.debian_slim("3.12")
        .run_commands(
            "apt-get update",
            "apt-get install -y git curl ca-certificates openssh-client",
        )
    )


async def _ensure_started(sandbox) -> None:
    state = getattr(sandbox, "state", None)
    state_val = state.value if hasattr(state, "value") else state
    if state_val in ("stopped", "archived"):
        logger.info("Resuming sandbox %s (state=%s)", sandbox.id, state_val)
        await sandbox.start()
        await sandbox.wait_for_sandbox_start()
    elif state_val in ("starting", "restoring"):
        await sandbox.wait_for_sandbox_start()


async def _ensure_git(sb) -> None:
    """Make sure git is available in the sandbox (safety net for existing sandboxes)."""
    resp = await sb.process.exec("which git 2>/dev/null || echo missing")
    if "missing" in (resp.result or ""):
        logger.info("git not found in sandbox — installing")
        await sb.process.exec(
            "apt-get update -qq && apt-get install -y -qq git curl ca-certificates 2>&1",
            timeout=60,
        )


async def get_sandbox():
    """Return the started persistent sandbox. Used by tools for native SDK access."""
    cfg = await get_configs()
    sandbox_id = (cfg.get("sandbox_id") or "").strip()
    if not sandbox_id:
        raise SandboxNotConfigured(
            "No sandbox yet. Open Settings → Daytona and click 'Create sandbox'."
        )
    client = await _get_client()
    try:
        sb = await client.get(sandbox_id)
    except Exception as e:
        raise SandboxNotConfigured(
            f"Stored sandbox {sandbox_id} is unavailable ({e}). "
            "Delete it from Settings and create a new one."
        ) from e
    await _ensure_started(sb)
    return sb


async def _clone_repo(sb, repo_url: str, pat: str) -> None:
    """Clone repo into sandbox with retry, branch fallback, and shell fallback.

    Tries branches: main → master → default. For each branch, tries native
    SDK git.clone first (3 attempts with backoff), then falls back to
    shell-based git clone. Raises exception if all attempts fail.
    """
    await _ensure_git(sb)

    last_err = None

    for branch in CLONE_BRANCHES:
        branch_label = branch or "(default)"
        logger.info("Cloning repo %s -> %s  branch=%s", repo_url, REPO_DIR, branch_label)

        for attempt in range(3):
            try:
                # Native SDK clone
                await sb.git.clone(
                    url=repo_url,
                    path=REPO_DIR,
                    branch=branch or None,
                    username="token",
                    password=pat,
                )
                logger.info("Repo cloned successfully via SDK (branch=%s)", branch_label)
                return
            except Exception as e:
                last_err = e
                err_msg = str(e).lower()
                # If the branch genuinely doesn't exist, don't retry — move to next
                if "remote ref" in err_msg or "not found" in err_msg or "does not exist" in err_msg:
                    logger.warning("Branch %s not found — trying next branch", branch_label)
                    break  # out of retry loop, try next branch
                logger.warning("SDK clone attempt %d/3 (branch=%s) failed: %s", attempt + 1, branch_label, e)
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))

        # --- Shell fallback for this branch ---
        logger.info("Trying shell clone for branch=%s", branch_label)
        try:
            auth_url = repo_url
            if repo_url.startswith("https://"):
                auth_url = repo_url.replace("https://", f"https://{pat}@")
            branch_arg = f"-b {branch} " if branch else ""
            resp = await sb.process.exec(
                f"rm -rf {REPO_DIR} && mkdir -p {REPO_DIR} && "
                f"git clone {branch_arg}{auth_url} {REPO_DIR} 2>&1",
                timeout=120,
            )
            if resp.exit_code == 0:
                logger.info("Repo cloned successfully via shell (branch=%s)", branch_label)
                return
            result = resp.result or ""
            if "Remote branch" in result or "not found" in result or "does not exist" in result:
                logger.warning("Branch %s not found via shell — trying next", branch_label)
                continue
            raise Exception(f"Shell clone exit {resp.exit_code}: {result}")
        except Exception as e2:
            logger.warning("Shell clone failed for branch=%s: %s", branch_label, e2)
            if any(kw in str(e2).lower() for kw in ("remote branch", "not found", "does not exist", "remote ref")):
                continue
            last_err = e2

    raise Exception(f"Repo clone failed after trying branches {CLONE_BRANCHES}. Last error: {last_err}")


async def create_sandbox() -> str:
    """Create a brand-new sandbox, persist its id, and clone the repo.

    Returns the new sandbox id.

    Raises SandboxCreateError with a user-friendly message on failure
    (including clone failure — the sandbox will be deleted if clone fails
    so no blank sandboxes are left behind).
    """
    client = await _get_client()

    # Read configurable specs from project config
    cfg = await get_configs()
    cpu = int(cfg.get("sandbox_cpu") or DEFAULT_CPU)
    memory = int(cfg.get("sandbox_memory") or DEFAULT_MEMORY)
    disk = int(cfg.get("sandbox_disk") or DEFAULT_DISK)

    params = CreateSandboxFromImageParams(
        language="python",
        image=_build_image(),
        resources=Resources(cpu=cpu, memory=memory, disk=disk),
    )
    try:
        sb = await client.create(params)
    except Exception as e:
        msg = str(e)
        logger.exception("Sandbox creation failed: %s", msg)
        hint = ""
        if "401" in msg or "unauthorized" in msg.lower() or "auth" in msg.lower():
            hint = " — Your Daytona API key may be invalid. Check Settings → Daytona."
        elif "402" in msg or "payment" in msg.lower() or "quota" in msg.lower() or "limit" in msg.lower():
            hint = " — Your Daytona account may have reached its quota or limit."
        elif "timeout" in msg.lower() or "connect" in msg.lower():
            hint = " — Could not reach Daytona API. Check your network."
        raise SandboxCreateError(f"Daytona sandbox creation failed: {msg}{hint}") from e

    await update_configs(sandbox_id=sb.id)
    logger.info("Created new sandbox: %s (cpu=%d, memory=%dGB, disk=%dGB)", sb.id, cpu, memory, disk)

    # Auto-clone repo if GitHub credentials are configured
    repo_url = (cfg.get("github_repo_url") or "").strip()
    pat = (cfg.get("github_pat") or "").strip()
    if repo_url and pat:
        try:
            await _clone_repo(sb, repo_url, pat)
        except Exception as e:
            logger.exception("Repo clone failed for sandbox %s", sb.id)
            # Clean up: delete the blank sandbox so user can retry
            try:
                await client.delete(sb)
            except Exception:
                logger.warning("Failed to clean up blank sandbox %s", sb.id)
            await update_configs(sandbox_id="")
            raise SandboxCreateError(
                f"Sandbox created but repo clone failed: {e}"
            ) from e
    else:
        logger.info("No GitHub credentials configured — skipping repo clone")

    return sb.id


async def delete_sandbox() -> dict:
    """Hard-delete the current sandbox via Daytona and clear the stored id."""
    cfg = await get_configs()
    sandbox_id = (cfg.get("sandbox_id") or "").strip()
    deleted = False
    error: str | None = None
    if sandbox_id:
        try:
            client = await _get_client()
            sb = await client.get(sandbox_id)
            await client.delete(sb)
            deleted = True
        except SandboxNotConfigured as e:
            error = str(e)
        except Exception as e:
            error = f"Daytona delete failed: {e}"
            logger.warning("Daytona delete %s failed: %s", sandbox_id, e)
    await update_configs(sandbox_id="")
    return {"deleted": deleted, "previous_id": sandbox_id, "error": error}


async def shell_exec(command: str, timeout: int = 120) -> dict:
    """Execute a shell command via process.exec (native SDK)."""
    try:
        sb = await get_sandbox()
    except SandboxNotConfigured as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1}
    try:
        resp = await sb.process.exec(command, timeout=timeout)
        return {
            "stdout": resp.result or "",
            "stderr": "",
            "exit_code": resp.exit_code,
        }
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1}
