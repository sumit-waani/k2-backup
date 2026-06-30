"""Reviewer subagent — fresh-context code review before git commit.

Architecture:
- Single non-streaming LLM call with full codebase + task + diff
- No conversation history, no tools, no accumulated context
- Returns structured verdict: approved/rejected with specific feedback
- Called automatically by the agent loop before git_commit

Design principle:
The reviewer has never seen the agent's reasoning, tool calls, or mistakes.
It evaluates the final code in isolation — exactly like a fresh code reviewer.
"""

import json
import logging
from typing import Optional

import httpx

from sandbox import shell_exec, REPO_DIR

logger = logging.getLogger(__name__)

REVIEWER_PROMPT = """\
You are a senior code reviewer. You are thorough, skeptical, and precise.

You receive:
1. The original task description
2. The full project codebase (current state)
3. The proposed changes (git diff)

Your job is to decide: should these changes ship?

## What to check

**Task completion:**
- Does the code actually solve the stated task? Not partially — fully.
- Are there requirements from the task that were missed or ignored?

**Bugs and correctness:**
- Are there logic errors, off-by-one errors, null/undefined risks?
- Are edge cases handled (empty input, missing data, boundary values)?
- Will this code crash or produce wrong results in any realistic scenario?

**Error handling:**
- Are errors caught and handled, or silently swallowed?
- Do error paths return useful information, or garbage?
- Are there bare try/except blocks that hide problems?

**Code quality:**
- Is the code unnecessarily complex? Could it be simpler?
- Are there hardcoded values that should be configurable?
- Is there duplicated logic that should be extracted?
- Does it match the style and patterns of the existing codebase?

**Regressions:**
- Does changing this break anything else that depends on it?
- Are there callers, imports, or references that need updating?
- Did the change modify existing behavior that other code relies on?

**Integration:**
- Does the new code integrate cleanly with the rest of the system?
- Are the interfaces (function signatures, data formats) consistent?
- Will this work in the actual runtime environment?

## What NOT to flag

Don't flag:
- Minor style preferences (tabs vs spaces, naming conventions that match existing code)
- Missing tests (unless the task specifically asked for tests)
- Documentation gaps (unless the task asked for docs)
- Hypothetical performance issues that won't manifest at realistic scale
- Things that are "different from how I'd do it" but are correct

## Output format

You MUST respond with ONLY a JSON object. No markdown, no explanation, no preamble.

{
  "approved": true/false,
  "issues": ["issue 1", "issue 2"],
  "feedback": "One paragraph summarizing what needs to change and why, or why the code is approved."
}

Be specific in feedback. "Fix error handling" is useless. "The shell_exec call in line X doesn't check exit_code, so a failed command silently returns empty output" is useful.

If the code is correct and ships cleanly:
{
  "approved": true,
  "issues": [],
  "feedback": "Code is correct. Changes match the task requirements, error handling is adequate, no regressions detected."
}
"""


async def gather_codebase() -> tuple[str, str]:
    """Gather full project context and diff.

    Returns (codebase_text, diff_text).
    Codebase_text includes project tree + all file contents.
    Diff_text is the git diff (unstaged at review time, since git add runs later).
    """
    # 1. Project tree
    tree_result = await shell_exec(
        f"cd {REPO_DIR} && find . -type f "
        "-not -path './.git/*' "
        "-not -path '*/node_modules/*' "
        "-not -path '*/__pycache__/*' "
        "-not -path '*/dist/*' "
        "-not -path '*/.venv/*' "
        "-not -path '*.pyc' "
        "-not -path '*.db' "
        "-not -path '*.lock' "
        "| sort",
        timeout=15,
    )
    tree = tree_result.get("stdout", "").strip()

    # 2. Read all files via a single Python script in the sandbox
    read_script = (
        f"cd {REPO_DIR} && python3 -c \"\n"
        "import os, sys\n"
        "skip = {'.git', 'node_modules', '__pycache__', 'dist', '.venv'}\n"
        "skip_ext = {'.pyc', '.db', '.lock', '.map', '.wasm', '.png', '.jpg', '.ico', '.svg'}\n"
        "for root, dirs, files in os.walk('.'):\n"
        "    dirs[:] = [d for d in dirs if d not in skip]\n"
        "    for f in sorted(files):\n"
        "        if os.path.splitext(f)[1] in skip_ext: continue\n"
        "        p = os.path.join(root, f)\n"
        "        try:\n"
        "            sz = os.path.getsize(p)\n"
        "            if sz > 200000: continue\n"
        "            with open(p, 'r', errors='replace') as fh:\n"
        "                c = fh.read()\n"
        "            print(f'===FILE:{p}===')\n"
        "            print(c)\n"
        "            print(f'===END:{p}===')\n"
        "        except: pass\n"
        "\""
    )
    files_result = await shell_exec(read_script, timeout=60)
    files_raw = files_result.get("stdout", "")

    # Parse file contents
    files_sections = []
    current_file = None
    current_lines = []

    for line in files_raw.split("\n"):
        if line.startswith("===FILE:") and line.endswith("==="):
            current_file = line[8:-3]
            current_lines = []
        elif line.startswith("===END:") and line.endswith("==="):
            if current_file and current_lines:
                content = "\n".join(current_lines)
                if len(content) > 40000:
                    content = content[:40000] + "\n... [file truncated at 40KB]"
                files_sections.append(f"\n{'='*60}\nFILE: {current_file}\n{'='*60}\n{content}")
            current_file = None
            current_lines = []
        elif current_file is not None:
            current_lines.append(line)

    codebase = f"## Project Tree\n\n{tree}\n\n## Source Files\n" + "\n".join(files_sections)

    # 3. Git diff (unstaged — agent changes are in working directory at this point)
    diff_result = await shell_exec(f"cd {REPO_DIR} && git diff 2>&1", timeout=15)
    diff = diff_result.get("stdout", "").strip()

    if not diff:
        diff_result = await shell_exec(f"cd {REPO_DIR} && git diff --cached 2>&1", timeout=15)
        diff = diff_result.get("stdout", "").strip()

    if not diff:
        diff = "(no diff — changes may not exist)"

    # Cap diff at 50k chars
    if len(diff) > 50000:
        diff = diff[:50000] + "\n\n... [diff truncated at 50KB]"

    return codebase, diff


async def run_reviewer(
    task_description: str,
    cfg: dict,
    timeout: float = 120.0,
) -> dict:
    """Run the reviewer subagent. Returns parsed verdict dict.

    Fail-closed on ALL errors except config errors (no LLM configured).
    If the reviewer can't reach the LLM, times out, or gets invalid output,
    the commit is BLOCKED — not silently approved.
    """
    base_url = cfg.get("llm1_url", "")
    api_key = cfg.get("llm1_api_key", "")
    model = cfg.get("llm1_model", "")

    if not base_url or not api_key or not model:
        logger.warning("Reviewer skipped — LLM not configured")
        return {
            "approved": True,
            "issues": [],
            "feedback": "Reviewer skipped — LLM not configured.",
        }

    # Gather full context
    logger.info("Reviewer: gathering codebase context...")
    codebase, diff = await gather_codebase()
    logger.info("Reviewer: codebase=%d chars, diff=%d chars", len(codebase), len(diff))

    # Build review prompt
    user_prompt = (
        f"## Task Description\n\n{task_description}\n\n"
        f"## Codebase (current state)\n\n{codebase}\n\n"
        f"## Proposed Changes (git diff)\n\n{diff}\n\n"
        "Review the proposed changes against the task and codebase. "
        "Respond with ONLY the JSON verdict."
    )

    prompt_size = len(user_prompt)
    logger.info("Reviewer: prompt size=%d chars", prompt_size)

    # LLM call (non-streaming)
    _b = base_url.rstrip("/")
    url = _b if _b.endswith("/chat/completions") else _b + "/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REVIEWER_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    content = ""  # Ensure defined for JSONDecodeError handler

    try:
        logger.info("Reviewer: calling LLM at %s (model=%s, timeout=%ds)...", url, model, timeout)
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as cx:
            resp = await cx.post(url, json=payload, headers=headers)

            if resp.status_code != 200:
                body = resp.text[:500]
                logger.error("Reviewer LLM HTTP %d: %s", resp.status_code, body)
                return {
                    "approved": False,
                    "issues": [f"Reviewer LLM returned HTTP {resp.status_code}"],
                    "feedback": f"Reviewer LLM returned HTTP {resp.status_code}: {body[:300]}",
                }

            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            if not content:
                logger.error("Reviewer returned empty response")
                return {
                    "approved": False,
                    "issues": ["Reviewer LLM returned empty response"],
                    "feedback": "Reviewer LLM returned an empty response. This usually means the model is overloaded or the prompt was too large.",
                }

            logger.info("Reviewer: LLM response (%d chars): %s", len(content), content[:300])

            # Parse JSON verdict (handle markdown code fences)
            clean = content
            if "```" in clean:
                start = clean.find("{")
                end = clean.rfind("}") + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]

            verdict = json.loads(clean)

            # Validate structure
            if "approved" not in verdict:
                raise ValueError("Missing 'approved' field")
            if "feedback" not in verdict:
                verdict["feedback"] = ""
            if "issues" not in verdict:
                verdict["issues"] = []

            logger.info("Reviewer: verdict parsed successfully — approved=%s", verdict.get("approved"))
            return verdict

    except json.JSONDecodeError as e:
        logger.error("Reviewer returned invalid JSON: %s — raw: %s", e, content[:200])
        return {
            "approved": False,
            "issues": ["Reviewer output was not valid JSON"],
            "feedback": (
                f"Reviewer could not produce a valid verdict. "
                f"Raw output: {content[:500]}"
            ),
        }
    except Exception as e:
        # FAIL-CLOSED: any error blocks the commit.
        # This includes timeouts, connection errors, DNS failures, etc.
        # The agent can retry the commit, and if the error persists,
        # it will exhaust review rounds and force-commit with a warning.
        logger.exception("Reviewer failed — blocking commit (fail-closed)")
        return {
            "approved": False,
            "issues": [f"Reviewer error: {type(e).__name__}: {str(e)[:200]}"],
            "feedback": (
                f"Reviewer failed with {type(e).__name__}: {e}\n"
                f"The commit was blocked because the reviewer could not complete. "
                f"Fix the issue or retry the commit."
            ),
        }
