"""Tests for the reviewer and code_review tool.

Tests verify:
1. Reviewer fail-closed on errors (timeouts, connection, HTTP, JSON)
2. Reviewer approves valid code
3. Reviewer rejects bad code
4. code_review tool works as a wrapper around run_reviewer
"""
import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# ── Stub out heavy dependencies before importing ──

daytona_sdk_mod = types.ModuleType("daytona_sdk")
for attr in ["AsyncDaytona", "DaytonaConfig", "CreateSandboxFromImageParams", "Image", "Resources"]:
    setattr(daytona_sdk_mod, attr, type(attr, (), {}))
sys.modules["daytona_sdk"] = daytona_sdk_mod

paramiko_mod = types.ModuleType("paramiko")
paramiko_mod.SSHClient = MagicMock
paramiko_mod.AutoAddPolicy = MagicMock
paramiko_mod.Ed25519Key = MagicMock
paramiko_mod.RSAKey = MagicMock
paramiko_mod.ECDSAKey = MagicMock
sys.modules["paramiko"] = paramiko_mod

aiosqlite_mod = types.ModuleType("aiosqlite")
aiosqlite_mod.Connection = type("Connection", (), {})
sys.modules["aiosqlite"] = aiosqlite_mod

sys.path.insert(0, "backend")
from reviewer import run_reviewer
from tools import _handle_code_review


# ══════════════════════════════════════════════════════════════
# Reviewer fail-closed tests
# ══════════════════════════════════════════════════════════════

async def test_fail_closed_on_timeout():
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    with patch("reviewer.gather_codebase", return_value=("code", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(side_effect=TimeoutError("timeout"))))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            v = await run_reviewer("task", cfg, timeout=1.0)
            assert v["approved"] is False, f"FAIL-OPEN: approved={v['approved']}"
            print("  ✓ timeout → approved=False")


async def test_fail_closed_on_connection():
    import httpx
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    with patch("reviewer.gather_codebase", return_value=("code", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(side_effect=httpx.ConnectError("refused"))))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            v = await run_reviewer("task", cfg, timeout=1.0)
            assert v["approved"] is False
            print("  ✓ connection error → approved=False")


async def test_skip_when_no_config():
    cfg = {"llm1_url": "", "llm1_api_key": "", "llm1_model": ""}
    v = await run_reviewer("task", cfg)
    assert v["approved"] is True
    print("  ✓ no config → approved=True (correct skip)")


async def test_fail_closed_on_http500():
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    resp = MagicMock(); resp.status_code = 500; resp.text = "err"
    with patch("reviewer.gather_codebase", return_value=("code", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=resp)))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            v = await run_reviewer("task", cfg, timeout=1.0)
            assert v["approved"] is False
            print("  ✓ HTTP 500 → approved=False")


async def test_approves_valid():
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    resp = MagicMock(); resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps(
        {"approved": True, "issues": [], "feedback": "Good."})}}]}
    with patch("reviewer.gather_codebase", return_value=("code", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=resp)))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            v = await run_reviewer("task", cfg, timeout=1.0)
            assert v["approved"] is True
            print("  ✓ valid code → approved=True")


async def test_rejects_bad():
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    resp = MagicMock(); resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps(
        {"approved": False, "issues": ["bug"], "feedback": "Fix it."})}}]}
    with patch("reviewer.gather_codebase", return_value=("code", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=resp)))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            v = await run_reviewer("task", cfg, timeout=1.0)
            assert v["approved"] is False
            assert len(v["issues"]) > 0
            print("  ✓ bad code → approved=False")


async def test_fail_closed_on_invalid_json():
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    resp = MagicMock(); resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "huh?"}}]}
    with patch("reviewer.gather_codebase", return_value=("code", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=resp)))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            v = await run_reviewer("task", cfg, timeout=1.0)
            assert v["approved"] is False
            print("  ✓ invalid JSON → approved=False")


# ══════════════════════════════════════════════════════════════
# code_review tool tests
# ══════════════════════════════════════════════════════════════

async def test_code_review_tool_approved():
    """code_review tool should return formatted output on approval."""
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    with patch("tools.get_configs", return_value=cfg):
        with patch("tools.run_reviewer", return_value={
            "approved": True, "issues": [], "feedback": "Looks good."
        }):
            result = await _handle_code_review({})
            assert "PASSED" in result
            assert "Looks good" in result
            print(f"  ✓ approved → {result[:80]}")


async def test_code_review_tool_rejected():
    """code_review tool should return formatted output on rejection."""
    cfg = {"llm1_url": "http://x/v1", "llm1_api_key": "k", "llm1_model": "m"}
    with patch("tools.get_configs", return_value=cfg):
        with patch("tools.run_reviewer", return_value={
            "approved": False, "issues": ["null check", "edge case"], "feedback": "Fix bugs."
        }):
            result = await _handle_code_review({"task_description": "add auth"})
            assert "FAILED" in result
            assert "null check" in result
            assert "Fix bugs" in result
            print(f"  ✓ rejected → {result[:80]}")


async def test_code_review_tool_no_config():
    """code_review tool should error when LLM not configured."""
    cfg = {"llm1_url": "", "llm1_api_key": "", "llm1_model": ""}
    with patch("tools.get_configs", return_value=cfg):
        result = await _handle_code_review({})
        assert "error" in result.lower() or "not configured" in result.lower()
        print(f"  ✓ no config → error")


# ══════════════════════════════════════════════════════════════
# Run
# ══════════════════════════════════════════════════════════════

async def main():
    tests = [
        ("Fail-closed on timeout", test_fail_closed_on_timeout),
        ("Fail-closed on connection", test_fail_closed_on_connection),
        ("Skip when no config", test_skip_when_no_config),
        ("Fail-closed on HTTP 500", test_fail_closed_on_http500),
        ("Approves valid code", test_approves_valid),
        ("Rejects bad code", test_rejects_bad),
        ("Fail-closed on invalid JSON", test_fail_closed_on_invalid_json),
        ("code_review tool: approved", test_code_review_tool_approved),
        ("code_review tool: rejected", test_code_review_tool_rejected),
        ("code_review tool: no config", test_code_review_tool_no_config),
    ]

    passed = failed = 0
    for name, fn in tests:
        print(f"\n{'─'*50}\nTEST: {name}\n{'─'*50}")
        try:
            await fn()
            passed += 1
            print("  ✅ PASSED")
        except Exception as e:
            failed += 1
            print(f"  ❌ FAILED: {e}")

    print(f"\n{'═'*50}\nRESULTS: {passed}/{passed+failed} passed\n{'═'*50}")
    return failed == 0

if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
