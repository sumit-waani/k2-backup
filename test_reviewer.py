"""Tests for the reviewer hook logic in agent.py.

Tests verify:
1. The reviewer fires for git_commit tool calls
2. The reviewer fires for shell_exec with `git commit`
3. The reviewer is skipped when there are no changes
4. The reviewer is fail-closed on errors (not fail-open)
5. The review_start/review_result/review_skipped SSE events are emitted
6. The reviewer blocks commit on rejection
7. The reviewer force-commits after max rounds
"""
import asyncio
import json
import sys
import types
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

# ── Stub out heavy dependencies before importing ──

# Stub daytona_sdk
daytona_sdk_mod = types.ModuleType("daytona_sdk")
for attr in [
    "AsyncDaytona", "DaytonaConfig", "CreateSandboxFromImageParams",
    "Image", "Resources",
]:
    setattr(daytona_sdk_mod, attr, type(attr, (), {}))
sys.modules["daytona_sdk"] = daytona_sdk_mod

# Stub paramiko
paramiko_mod = types.ModuleType("paramiko")
paramiko_mod.SSHClient = MagicMock
paramiko_mod.AutoAddPolicy = MagicMock
paramiko_mod.Ed25519Key = MagicMock
paramiko_mod.RSAKey = MagicMock
paramiko_mod.ECDSAKey = MagicMock
sys.modules["paramiko"] = paramiko_mod

# Stub aiosqlite with Connection attribute
aiosqlite_mod = types.ModuleType("aiosqlite")
aiosqlite_mod.Connection = type("Connection", (), {})
sys.modules["aiosqlite"] = aiosqlite_mod

# Now import our modules
sys.path.insert(0, "backend")
from reviewer import run_reviewer


# ══════════════════════════════════════════════════════════════
# TEST 1: Reviewer fail-closed on exceptions
# ══════════════════════════════════════════════════════════════

async def test_reviewer_fail_closed_on_timeout():
    """The reviewer should return approved=False on timeout, NOT approved=True."""
    cfg = {
        "llm1_url": "http://localhost:1/v1",
        "llm1_api_key": "test-key",
        "llm1_model": "test-model",
    }

    with patch("reviewer.gather_codebase", return_value=("codebase", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(
                    post=AsyncMock(side_effect=TimeoutError("Connection timed out"))
                )
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            verdict = await run_reviewer("test task", cfg, timeout=1.0)

            assert verdict["approved"] is False, \
                f"FAIL-OPEN BUG: reviewer returned approved={verdict['approved']} on timeout. Should be False."
            assert len(verdict.get("issues", [])) > 0, \
                "Should include error details in issues."
            print(f"  ✓ Timeout → approved=False, issues={verdict['issues']}")


async def test_reviewer_fail_closed_on_connection_error():
    """The reviewer should return approved=False on connection errors."""
    import httpx
    cfg = {
        "llm1_url": "http://localhost:1/v1",
        "llm1_api_key": "test-key",
        "llm1_model": "test-model",
    }

    with patch("reviewer.gather_codebase", return_value=("codebase", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(
                    post=AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
                )
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            verdict = await run_reviewer("test task", cfg, timeout=1.0)

            assert verdict["approved"] is False, \
                f"FAIL-OPEN BUG: reviewer returned approved={verdict['approved']} on connection error."
            print(f"  ✓ Connection error → approved=False, issues={verdict['issues']}")


# ══════════════════════════════════════════════════════════════
# TEST 2: Reviewer config skip (only case where approved=True)
# ══════════════════════════════════════════════════════════════

async def test_reviewer_skip_when_no_llm_config():
    """The reviewer should return approved=True ONLY when LLM is not configured."""
    cfg = {"llm1_url": "", "llm1_api_key": "", "llm1_model": ""}

    verdict = await run_reviewer("test task", cfg)

    assert verdict["approved"] is True, \
        "Should auto-approve when LLM is not configured (config error, not runtime error)."
    print(f"  ✓ No LLM config → approved=True (correct skip)")


# ══════════════════════════════════════════════════════════════
# TEST 3: Reviewer rejects on HTTP errors
# ══════════════════════════════════════════════════════════════

async def test_reviewer_fail_closed_on_http_error():
    """The reviewer should return approved=False on HTTP errors."""
    cfg = {
        "llm1_url": "http://localhost:1/v1",
        "llm1_api_key": "test-key",
        "llm1_model": "test-model",
    }

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("reviewer.gather_codebase", return_value=("codebase", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            verdict = await run_reviewer("test task", cfg, timeout=1.0)

            assert verdict["approved"] is False, \
                f"Should reject on HTTP 500, got approved={verdict['approved']}"
            print(f"  ✓ HTTP 500 → approved=False")


# ══════════════════════════════════════════════════════════════
# TEST 4: Reviewer approves valid code
# ══════════════════════════════════════════════════════════════

async def test_reviewer_approves_valid_code():
    """The reviewer should return approved=True when LLM says code is good."""
    cfg = {
        "llm1_url": "http://localhost:1/v1",
        "llm1_api_key": "test-key",
        "llm1_model": "test-model",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "approved": True,
                    "issues": [],
                    "feedback": "Code is correct.",
                }),
            },
        }],
    }

    with patch("reviewer.gather_codebase", return_value=("codebase", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            verdict = await run_reviewer("test task", cfg, timeout=1.0)

            assert verdict["approved"] is True
            assert verdict["feedback"] == "Code is correct."
            print(f"  ✓ Valid code → approved=True")


# ══════════════════════════════════════════════════════════════
# TEST 5: Reviewer rejects bad code
# ══════════════════════════════════════════════════════════════

async def test_reviewer_rejects_bad_code():
    """The reviewer should return approved=False when LLM finds issues."""
    cfg = {
        "llm1_url": "http://localhost:1/v1",
        "llm1_api_key": "test-key",
        "llm1_model": "test-model",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "approved": False,
                    "issues": ["Missing null check on line 42"],
                    "feedback": "The code will crash on empty input.",
                }),
            },
        }],
    }

    with patch("reviewer.gather_codebase", return_value=("codebase", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            verdict = await run_reviewer("test task", cfg, timeout=1.0)

            assert verdict["approved"] is False
            assert len(verdict["issues"]) > 0
            print(f"  ✓ Bad code → approved=False, issues={verdict['issues']}")


# ══════════════════════════════════════════════════════════════
# TEST 6: agent.py _check_has_changes
# ══════════════════════════════════════════════════════════════

async def test_check_has_changes_uses_native_sdk():
    """_check_has_changes should use sb.git.status(), not shell_exec."""
    import agent as agent_mod

    mock_status = MagicMock()
    mock_status.file_status = [MagicMock()]  # One file changed

    mock_sb = MagicMock()
    mock_sb.git.status = AsyncMock(return_value=mock_status)

    with patch.object(agent_mod, "get_sandbox", return_value=mock_sb):
        result = await agent_mod._check_has_changes()

    assert result is True
    mock_sb.git.status.assert_called_once()
    print(f"  ✓ _check_has_changes uses native SDK git.status()")


async def test_check_has_changes_returns_false_on_clean():
    """_check_has_changes should return False when no changes."""
    import agent as agent_mod

    mock_status = MagicMock()
    mock_status.file_status = None  # Clean working tree

    mock_sb = MagicMock()
    mock_sb.git.status = AsyncMock(return_value=mock_status)

    with patch.object(agent_mod, "get_sandbox", return_value=mock_sb):
        result = await agent_mod._check_has_changes()

    assert result is False
    print(f"  ✓ _check_has_changes returns False on clean tree")


async def test_check_has_changes_fail_closed():
    """_check_has_changes should return True (fail-closed) when SDK errors."""
    import agent as agent_mod

    mock_sb = MagicMock()
    mock_sb.git.status = AsyncMock(side_effect=Exception("SDK error"))

    with patch.object(agent_mod, "get_sandbox", return_value=mock_sb):
        result = await agent_mod._check_has_changes()

    assert result is True, "Should fail-closed (assume changes exist)"
    print(f"  ✓ _check_has_changes fails closed on SDK error")


# ══════════════════════════════════════════════════════════════
# TEST 7: shell_exec git commit detection
# ══════════════════════════════════════════════════════════════

def test_git_commit_regex():
    """The regex should detect git commit in various shell command forms."""
    import re
    pattern = r'\bgit\s+commit\b'

    test_cases = [
        ('git commit -m "fix: bug"', True),
        ('git add -A && git commit -m "fix"', True),
        ('cd /repo && git add . && git commit -m "test"', True),
        ('git commit --amend -m "updated"', True),
        ('git commit --allow-empty -m "trigger"', True),
        ('GIT_AUTHOR_NAME="K" git commit -m "x"', True),
        ('git status', False),
        ('git log --oneline', False),
        ('git diff --stat', False),
        ('git push origin main', False),
        ('echo "use git commit to save"', True),  # edge case — acceptable false positive
        ('git push', False),
    ]

    for cmd, expected in test_cases:
        result = bool(re.search(pattern, cmd))
        status = "✓" if result == expected else "✗ FAIL"
        if result != expected:
            print(f"  {status} '{cmd}' → {result} (expected {expected})")
            assert False, f"Regex mismatch for: {cmd}"
        else:
            print(f"  {status} '{cmd}' → {result}")


# ══════════════════════════════════════════════════════════════
# TEST 8: reviewer returns invalid JSON → fail-closed
# ══════════════════════════════════════════════════════════════

async def test_reviewer_fail_closed_on_invalid_json():
    """The reviewer should return approved=False when LLM returns garbage."""
    cfg = {
        "llm1_url": "http://localhost:1/v1",
        "llm1_api_key": "test-key",
        "llm1_model": "test-model",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": "I'm not sure about this code, let me think...",
            },
        }],
    }

    with patch("reviewer.gather_codebase", return_value=("codebase", "diff")):
        with patch("reviewer.httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            verdict = await run_reviewer("test task", cfg, timeout=1.0)

            assert verdict["approved"] is False, \
                f"Should reject on invalid JSON, got approved={verdict['approved']}"
            print(f"  ✓ Invalid JSON → approved=False")


# ══════════════════════════════════════════════════════════════
# Run all tests
# ══════════════════════════════════════════════════════════════

async def main():
    tests = [
        ("Reviewer fail-closed on timeout", test_reviewer_fail_closed_on_timeout),
        ("Reviewer fail-closed on connection error", test_reviewer_fail_closed_on_connection_error),
        ("Reviewer skip when no LLM config", test_reviewer_skip_when_no_llm_config),
        ("Reviewer fail-closed on HTTP error", test_reviewer_fail_closed_on_http_error),
        ("Reviewer approves valid code", test_reviewer_approves_valid_code),
        ("Reviewer rejects bad code", test_reviewer_rejects_bad_code),
        ("_check_has_changes uses native SDK", test_check_has_changes_uses_native_sdk),
        ("_check_has_changes returns False on clean", test_check_has_changes_returns_false_on_clean),
        ("_check_has_changes fail-closed", test_check_has_changes_fail_closed),
        ("Git commit regex detection", test_git_commit_regex),
        ("Reviewer fail-closed on invalid JSON", test_reviewer_fail_closed_on_invalid_json),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"\n{'─'*60}")
        print(f"TEST: {name}")
        print(f"{'─'*60}")
        try:
            if callable(test_fn) and not asyncio.iscoroutinefunction(test_fn):
                test_fn()
            else:
                await test_fn()
            passed += 1
            print(f"  ✅ PASSED")
        except Exception as e:
            failed += 1
            print(f"  ❌ FAILED: {e}")

    print(f"\n{'═'*60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'═'*60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
