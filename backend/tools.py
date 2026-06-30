"""Tool implementations for the agent.

Tools are the agent's interface to the world. Each tool:
1. Has a schema (OpenAI function-calling format)
2. Has an async implementation
3. Returns a string result (no truncation — LLM has 1M context)
4. Never throws — errors are returned as strings

Native Daytona SDK APIs used for git and filesystem operations.
Shell/exec uses process.exec. VPS uses paramiko SSH.
"""
import asyncio
import io
import json
import logging
import re
from typing import Any

import httpx
import paramiko

from db import get_configs, update_configs
from sandbox import shell_exec, get_sandbox, REPO_DIR

logger = logging.getLogger(__name__)

# Kaptaan identity for git commits
GIT_AUTHOR = "Kaptaan"
GIT_EMAIL = "kaptaan@om.kaptaan.dev"

def _error(tool: str, msg: str) -> str:
    """Format a tool error consistently."""
    return f"[{tool} error] {msg}"

async def _get_github_creds() -> tuple[str, str]:
    """Get (repo_url, pat) from config. Returns empty strings if not set."""
    cfg = await get_configs()
    return (cfg.get("github_repo_url") or "").strip(), (cfg.get("github_pat") or "").strip()

# ---------- Tool schemas (OpenAI function-calling format) ----------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": (
                "Execute a shell command in the persistent Daytona Python sandbox. "
                "Use for running code, installing packages, file ops, git, curl, etc. "
                "The sandbox is persistent — files survive across calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": (
                "Read a file from the Daytona sandbox. Returns the file contents. "
                "Use for reading code, configs, logs, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path in the sandbox",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start from (0-based). Default: 0",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to read. Default: 500. Use 0 for all.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": (
                "Write content to a file in the Daytona sandbox. Creates parent "
                "directories if needed. Overwrites existing files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path in the sandbox",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "If true, append to file instead of overwriting. Default: false",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vps_exec",
            "description": (
                "Execute a shell command on the configured VPS over SSH. "
                "Credentials are read from VPS settings. "
                "Use for deployments, server inspection, log tailing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute on the VPS",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": (
                "Make an HTTP request. Supports GET, POST, PUT, DELETE, PATCH. "
                "Returns response body, status code, and headers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to request"},
                    "method": {"type": "string", "description": "HTTP method. Default: GET", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]},
                    "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)"},
                    "headers": {"type": "object", "description": "Additional headers"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using Firecrawl. Returns snippets and URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "url_fetch",
            "description": "Fetch and convert a URL to clean markdown via Firecrawl.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": "Read the full markdown memory document. Always call this first before any task.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": "Overwrite the memory document. Read first, then update with complete new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Full updated markdown content"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scratchpad_read",
            "description": "Read the scratchpad content. Use this to load your working plan before multi-step tasks.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scratchpad_write",
            "description": "Write content to the scratchpad. Use this to track your working plan for multi-step tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to write to the scratchpad"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_clone",
            "description": (
                "Clone or pull the configured GitHub repository into the sandbox. "
                "Uses native Daytona SDK. Repo is cloned to " + REPO_DIR + ". "
                "If repo already exists, pulls latest changes. "
                "GitHub URL and PAT must be set in Settings → GitHub."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch to clone. Default: main",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get the git status of the repository. Shows current branch, modified/added/deleted files.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "Stage all changes and commit with a message. "
                "Auto-stages all files (git add -A equivalent). "
                "Identity: Kaptaan <kaptaan@om.kaptaan.dev>."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_push",
            "description": (
                "Push the current branch to the remote repository. "
                "Uses PAT authentication internally — agent never sees credentials. "
                "GitHub URL and PAT must be set in Settings → GitHub."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch to push. Default: current branch",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_pull",
            "description": "Pull latest changes from remote. Uses PAT authentication internally.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff of changes. Shows unstaged changes by default, or staged changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged changes instead of unstaged. Default: false",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Show recent git log. Returns commit history with hashes, authors, dates, and messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of recent commits to show. Default: 10",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": "List all branches or create/switch/delete branches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "create", "switch", "delete"],
                        "description": "Action to perform. Default: list",
                    },
                    "name": {
                        "type": "string",
                        "description": "Branch name (required for create/switch/delete)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_pr_create",
            "description": (
                "Create a GitHub Pull Request. Pushes the current branch first, "
                "then creates a PR via GitHub API. "
                "GitHub URL and PAT must be set in Settings → GitHub."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "PR title",
                    },
                    "body": {
                        "type": "string",
                        "description": "PR description/body",
                    },
                    "base": {
                        "type": "string",
                        "description": "Base branch to merge into. Default: main",
                    },
                    "head": {
                        "type": "string",
                        "description": "Head branch (current branch if not specified)",
                    },
                },
                "required": ["title"],
            },
        },
    },
]

# ---------- Tool implementations ----------

async def _handle_shell_exec(args: dict) -> str:
    command = args.get("command", "")
    if not command:
        return _error("shell_exec", "No command provided.")
    r = await shell_exec(command)
    parts = []
    if r.get("stdout"):
        parts.append(r["stdout"].strip())
    if r.get("stderr"):
        parts.append(f"[stderr]\n{r['stderr'].strip()}")
    if r.get("exit_code", -1) != 0:
        parts.append(f"[exit_code: {r['exit_code']}]")
    return "\n".join(parts) if parts else "(no output)"

async def _handle_file_read(args: dict) -> str:
    path = args.get("path", "")
    if not path:
        return _error("file_read", "No path provided.")
    offset = args.get("offset", 0)
    limit = args.get("limit", 500)
    try:
        sb = await get_sandbox()
        content = await sb.fs.download_file(path)
        if content is None:
            return _error("file_read", f"File not found: {path}")
        text = content.decode("utf-8", errors="replace")
        lines = text.split("\n")
        if offset > 0:
            lines = lines[offset:]
        if limit and limit > 0:
            lines = lines[:limit]
        result = "\n".join(lines)
        if not result.strip():
            return f"(empty file: {path})"
        return result
    except Exception as e:
        return _error("file_read", str(e))

async def _handle_file_write(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    append = args.get("append", False)
    if not path:
        return _error("file_write", "No path provided.")
    try:
        sb = await get_sandbox()
        if append:
            try:
                existing = await sb.fs.download_file(path)
                if existing:
                    content = existing.decode("utf-8", errors="replace") + content
            except Exception:
                pass  # File doesn't exist yet, just write
        import os
        parent = os.path.dirname(path)
        if parent:
            await sb.process.exec(f"mkdir -p {parent}")
        await sb.fs.upload_file(content.encode("utf-8"), path)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return _error("file_write", str(e))

async def _handle_vps_exec(args: dict) -> str:
    command = args.get("command", "")
    if not command:
        return _error("vps_exec", "No command provided.")
    cfg = await get_configs()
    host = (cfg.get("vps_host") or "").strip()
    port = int(cfg.get("vps_port") or 22)
    username = (cfg.get("vps_username") or "").strip()
    password = (cfg.get("vps_password") or "").strip()
    ssh_key = (cfg.get("vps_ssh_key") or "").strip()
    if not host or not username:
        return _error("vps_exec", "VPS not configured. Open Settings → VPS.")
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs: dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": 30,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if ssh_key:
            pkey = None
            for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
                try:
                    pkey = cls.from_private_key(io.StringIO(ssh_key))
                    break
                except Exception:
                    continue
            if pkey is None:
                return _error("vps_exec", "Could not parse SSH private key. Supported: Ed25519, RSA, ECDSA.")
            connect_kwargs["pkey"] = pkey
        elif password:
            connect_kwargs["password"] = password
        else:
            return _error("vps_exec", "No SSH key or password configured.")
        client.connect(**connect_kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=120)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        parts = []
        if out.strip():
            parts.append(out.strip())
        if err.strip():
            parts.append(f"[stderr]\n{err.strip()}")
        if exit_code != 0:
            parts.append(f"[exit_code: {exit_code}]")
        return "\n".join(parts) if parts else "(no output)"
    except Exception as e:
        return _error("vps_exec", str(e))

async def _handle_http_request(args: dict) -> str:
    url = args.get("url", "")
    if not url:
        return _error("http_request", "No URL provided.")
    method = args.get("method", "GET").upper()
    body = args.get("body")
    headers = args.get("headers", {})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, content=body, headers=headers)
            result_parts = [f"[{resp.status_code}]"]
            try:
                data = resp.json()
                result_parts.append(json.dumps(data, indent=2, ensure_ascii=False))
            except Exception:
                result_parts.append(resp.text)
            return "\n".join(result_parts)
    except Exception as e:
        return _error("http_request", str(e))

async def _handle_web_search(args: dict) -> str:
    query = args.get("query", "")
    if not query:
        return _error("web_search", "No query provided.")
    cfg = await get_configs()
    firecrawl_key = (cfg.get("firecrawl_key") or "").strip()
    if not firecrawl_key:
        return _error("web_search", "Firecrawl API key not set. Open Settings → Firecrawl.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v2/search",
                headers={"Authorization": f"Bearer {firecrawl_key}", "Content-Type": "application/json"},
                json={"query": query, "limit": 5, "scrapeOptions": {"formats": ["markdown"]}},
            )
            data = resp.json()
            inner = data.get("data", {})
            results = inner.get("web", inner.get("results", []))
            if not results:
                return f"No results found for: {query}"
            parts = []
            for r in results[:5]:
                title = r.get("title", r.get("url", "No title"))
                url = r.get("url", "")
                snippet = r.get("markdown", r.get("snippet", r.get("description", "")))
                parts.append(f"### {title}\nURL: {url}\n{snippet}\n")
            return "\n---\n".join(parts)
    except Exception as e:
        return _error("web_search", str(e))

async def _handle_url_fetch(args: dict) -> str:
    url = args.get("url", "")
    if not url:
        return _error("url_fetch", "No URL provided.")
    cfg = await get_configs()
    firecrawl_key = (cfg.get("firecrawl_key") or "").strip()
    if not firecrawl_key:
        return _error("url_fetch", "Firecrawl API key not set. Open Settings → Firecrawl.")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v2/scrape",
                headers={"Authorization": f"Bearer {firecrawl_key}", "Content-Type": "application/json"},
                json={"url": url, "formats": ["markdown"]},
            )
            data = resp.json()
            content = data.get("data", {}).get("markdown", "")
            if not content:
                content = data.get("data", {}).get("content", "")
            if not content:
                return f"No content extracted from: {url}"
            return content
    except Exception as e:
        return _error("url_fetch", str(e))

async def _handle_memory_read(args: dict) -> str:
    cfg = await get_configs()
    memory = (cfg.get("memory") or "").strip()
    if not memory:
        return "(empty — no memory stored yet)"
    return memory

async def _handle_memory_update(args: dict) -> str:
    content = args.get("content", "")
    if not content:
        return _error("memory_update", "No content provided.")
    await update_configs(memory=content)
    return f"Memory updated ({len(content)} chars)"

async def _handle_scratchpad_read(args: dict) -> str:
    cfg = await get_configs()
    content = (cfg.get("scratchpad") or "").strip()
    if not content:
        return "(empty scratchpad)"
    return content

async def _handle_scratchpad_write(args: dict) -> str:
    content = args.get("content", "")
    if not content:
        return _error("scratchpad_write", "No content provided.")
    await update_configs(scratchpad=content)
    return f"Scratchpad updated ({len(content)} chars)"

# ---------- Git tool handlers (Native Daytona SDK) ----------

async def _handle_git_clone(args: dict) -> str:
    """Clone or pull the configured repo using native SDK."""
    repo_url, pat = await _get_github_creds()
    if not repo_url or not pat:
        return _error("git_clone", "GitHub repo URL and PAT must be configured in Settings → GitHub.")
    branch = args.get("branch", "main")
    try:
        sb = await get_sandbox()
        try:
            status = await sb.git.status(REPO_DIR)
            await sb.git.pull(REPO_DIR, username="token", password=pat)
            return f"Repo exists at {REPO_DIR}. Pulled latest changes. Branch: {status.current_branch}"
        except Exception:
            await sb.git.clone(
                url=repo_url,
                path=REPO_DIR,
                branch=branch,
                username="token",
                password=pat,
            )
            return f"Cloned repo to {REPO_DIR} (branch: {branch})"
    except Exception as e:
        return _error("git_clone", str(e))

async def _handle_git_status(args: dict) -> str:
    """Get repo status using native SDK."""
    try:
        sb = await get_sandbox()
        status = await sb.git.status(REPO_DIR)
        parts = [f"Branch: {status.current_branch}"]
        if status.ahead:
            parts.append(f"Ahead: {status.ahead}")
        if status.behind:
            parts.append(f"Behind: {status.behind}")
        if status.file_status:
            staged = []
            unstaged = []
            untracked = []
            for fs in status.file_status:
                name = fs.name
                staging = getattr(fs, 'staging', None)
                worktree = getattr(fs, 'worktree', None)
                staging_val = staging.value if hasattr(staging, 'value') else str(staging) if staging else None
                worktree_val = worktree.value if hasattr(worktree, 'value') else str(worktree) if worktree else None
                if staging_val and staging_val not in ('unmodified', 'None', ''):
                    staged.append(f"  {staging_val}: {name}")
                if worktree_val and worktree_val not in ('unmodified', 'None', ''):
                    unstaged.append(f"  {worktree_val}: {name}")
                if staging_val == 'untracked' or worktree_val == 'untracked':
                    untracked.append(f"  {name}")
            if staged:
                parts.append("\nStaged:\n" + "\n".join(staged))
            if unstaged:
                parts.append("\nUnstaged:\n" + "\n".join(unstaged))
            if untracked:
                parts.append("\nUntracked:\n" + "\n".join(untracked))
            if not staged and not unstaged and not untracked:
                parts.append("\nWorking tree clean")
        else:
            parts.append("\nWorking tree clean")
        return "\n".join(parts)
    except Exception as e:
        return _error("git_status", str(e))

async def _handle_git_commit(args: dict) -> str:
    """Stage all and commit using native SDK."""
    message = args.get("message", "")
    if not message:
        return _error("git_commit", "No commit message provided.")
    try:
        sb = await get_sandbox()
        await sb.git.add(REPO_DIR, ["."])
        result = await sb.git.commit(
            path=REPO_DIR,
            message=message,
            author=GIT_AUTHOR,
            email=GIT_EMAIL,
        )
        return f"Committed: {result.sha[:12]} — {message}"
    except Exception as e:
        return _error("git_commit", str(e))

async def _handle_git_push(args: dict) -> str:
    """Push to remote using native SDK with PAT auth."""
    _, pat = await _get_github_creds()
    if not pat:
        return _error("git_push", "GitHub PAT must be configured in Settings → GitHub.")
    try:
        sb = await get_sandbox()
        await sb.git.push(REPO_DIR, username="token", password=pat)
        return "Pushed successfully."
    except Exception as e:
        return _error("git_push", str(e))

async def _handle_git_pull(args: dict) -> str:
    """Pull from remote using native SDK with PAT auth."""
    _, pat = await _get_github_creds()
    if not pat:
        return _error("git_pull", "GitHub PAT must be configured in Settings → GitHub.")
    try:
        sb = await get_sandbox()
        await sb.git.pull(REPO_DIR, username="token", password=pat)
        return "Pulled latest changes."
    except Exception as e:
        return _error("git_pull", str(e))

async def _handle_git_diff(args: dict) -> str:
    """Show diff using process.exec (SDK has no native diff)."""
    staged = args.get("staged", False)
    flag = "--cached" if staged else ""
    r = await shell_exec(f"cd {REPO_DIR} && git diff {flag} 2>&1")
    if r.get("exit_code", -1) != 0:
        return _error("git_diff", r.get("stderr") or r.get("stdout", "diff failed"))
    output = r.get("stdout", "").strip()
    if not output:
        return "No changes."
    return output

async def _handle_git_log(args: dict) -> str:
    """Show log using process.exec (SDK has no native log)."""
    count = args.get("count", 10)
    r = await shell_exec(f"cd {REPO_DIR} && git log --oneline -{count} 2>&1")
    if r.get("exit_code", -1) != 0:
        return _error("git_log", r.get("stderr") or r.get("stdout", "log failed"))
    output = r.get("stdout", "").strip()
    if not output:
        return "No commits yet."
    return output

async def _handle_git_branch(args: dict) -> str:
    """Manage branches using native SDK."""
    action = args.get("action", "list")
    name = args.get("name", "")
    try:
        sb = await get_sandbox()
        if action == "list":
            resp = await sb.git.branches(REPO_DIR)
            branches = resp.branches or []
            return "Branches:\n" + "\n".join(f"  • {b}" for b in branches)
        elif action == "create":
            if not name:
                return _error("git_branch", "Branch name required for create.")
            await sb.git.create_branch(REPO_DIR, name)
            return f"Created branch: {name}"
        elif action == "switch":
            if not name:
                return _error("git_branch", "Branch name required for switch.")
            await sb.git.checkout_branch(REPO_DIR, name)
            return f"Switched to branch: {name}"
        elif action == "delete":
            if not name:
                return _error("git_branch", "Branch name required for delete.")
            await sb.git.delete_branch(REPO_DIR, name)
            return f"Deleted branch: {name}"
        else:
            return _error("git_branch", f"Unknown action: {action}")
    except Exception as e:
        return _error("git_branch", str(e))

async def _handle_git_pr_create(args: dict) -> str:
    """Create a GitHub PR. Push first, then create PR via API."""
    title = args.get("title", "")
    if not title:
        return _error("git_pr_create", "PR title is required.")
    body = args.get("body", "")
    base = args.get("base", "main")
    repo_url, pat = await _get_github_creds()
    if not repo_url or not pat:
        return _error("git_pr_create", "GitHub repo URL and PAT must be configured.")

    # Push first
    try:
        sb = await get_sandbox()
        await sb.git.push(REPO_DIR, username="token", password=pat)
    except Exception as e:
        return _error("git_pr_create", f"Push failed: {e}")

    # Get current branch name
    try:
        sb = await get_sandbox()
        status = await sb.git.status(REPO_DIR)
        head = args.get("head", status.current_branch)
    except Exception:
        head = args.get("head", "main")

    # Extract owner/repo from URL
    match = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", repo_url)
    if not match:
        return _error("git_pr_create", f"Cannot parse GitHub URL: {repo_url}")
    owner, repo = match.group(1), match.group(2)

    # Create PR via GitHub API
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers={
                    "Authorization": f"token {pat}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={"title": title, "body": body, "head": head, "base": base},
            )
            if resp.status_code == 201:
                pr = resp.json()
                return f"PR created: #{pr['number']} — {pr['title']}\nURL: {pr['html_url']}"
            else:
                return _error("git_pr_create", f"GitHub API {resp.status_code}: {resp.text[:500]}")
    except Exception as e:
        return _error("git_pr_create", str(e))

# ---------- Tool router ----------

TOOL_HANDLERS = {
    "shell_exec": _handle_shell_exec,
    "file_read": _handle_file_read,
    "file_write": _handle_file_write,
    "vps_exec": _handle_vps_exec,
    "http_request": _handle_http_request,
    "web_search": _handle_web_search,
    "url_fetch": _handle_url_fetch,
    "memory_read": _handle_memory_read,
    "memory_update": _handle_memory_update,
    "scratchpad_read": _handle_scratchpad_read,
    "scratchpad_write": _handle_scratchpad_write,
    "git_clone": _handle_git_clone,
    "git_status": _handle_git_status,
    "git_commit": _handle_git_commit,
    "git_push": _handle_git_push,
    "git_pull": _handle_git_pull,
    "git_diff": _handle_git_diff,
    "git_log": _handle_git_log,
    "git_branch": _handle_git_branch,
    "git_pr_create": _handle_git_pr_create,
}

async def run_tool(name: str, arguments: dict) -> str:
    """Run a tool by name. Never throws — returns error string on failure."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return _error(name, f"Unknown tool: {name}")
    try:
        return await handler(arguments)
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return _error(name, str(e))
