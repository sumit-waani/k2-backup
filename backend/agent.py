"""ReAct agent loop with SSE streaming over an OpenAI-compatible LLM.

Architecture:
- Single agent, multi-step ReAct loop (up to 250 steps)
- Each step: LLM thinks → decides to use tool or tool executes → repeat
- Tool results are fed back to the LLM as tool messages
- The final text response ends the loop
- All events are streamed to the frontend via SSE

Context management:
- Full history is loaded from DB (messages table) every turn
- No automatic trimming — user controls context manually via UI delete
"""
import json
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx

from db import execute, fetch_all, get_configs, new_id, now_iso
from tools import TOOL_SCHEMAS, run_tool

logger = logging.getLogger(__name__)

MAX_STEPS = 250

# Load default system prompt from SYSTEM_PROMPT.md if it exists
_PROMPT_FILE = Path(__file__).parent.parent / "SYSTEM_PROMPT.md"
_FALLBACK_PROMPT = (
    "You are Kaptaan — the technical co-owner. Not an assistant.\n"
    "Before any task: memory_read → scratchpad_write your plan as a checklist.\n"
    "Work protocol: Orient → Read → Test First → Implement → Verify → Ship.\n"
    "Use codebase_search to find patterns before writing code.\n"
    "Write tests first, confirm they fail, implement, confirm they pass.\n"
    "Check off subtasks in scratchpad as you complete them.\n"
    "If stuck 3 times on same approach, stop and reassess.\n"
    "Use git_commit + git_push to ship. Be concise. Report outcomes, not process."
)


def _load_default_prompt() -> str:
    """Load system prompt from SYSTEM_PROMPT.md, or use hardcoded fallback."""
    try:
        return _PROMPT_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return _FALLBACK_PROMPT


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _load_history() -> list[dict]:
    """Load full message history for the LLM context.

    Messages are stored as JSON objects with rich content (text + tool calls + results).
    This converts them back to the flat OpenAI message format the LLM expects.
    No limit — user manages context manually via UI delete.
    """
    rows = await fetch_all(
        "SELECT role, content FROM messages ORDER BY created_at ASC"
    )
    out: list[dict] = []
    for r in rows:
        try:
            parsed = json.loads(r["content"])

            # Rich message format: {content: [...parts]}
            if isinstance(parsed, dict) and "content" in parsed and isinstance(parsed["content"], list):
                msg = {"role": r["role"]}
                text_parts = []
                tool_calls = []
                for part in parsed["content"]:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part["text"])
                        elif part.get("type") == "tool_call":
                            tool_calls.append({
                                "id": part["id"],
                                "type": "function",
                                "function": {
                                    "name": part["name"],
                                    "arguments": part["arguments"],
                                },
                            })
                    elif isinstance(part, str):
                        text_parts.append(part)
                msg["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                out.append(msg)
                # Emit tool results as separate messages for the LLM
                for part in parsed["content"]:
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        out.append({
                            "role": "tool",
                            "tool_call_id": part["id"],
                            "content": part["output"],
                        })
                continue
            # Legacy JSON format: {role, content}
            if isinstance(parsed, dict) and "role" in parsed:
                out.append(parsed)
                continue
        except (json.JSONDecodeError, TypeError):
            pass
        # Plain text fallback
        out.append({"role": r["role"], "content": r["content"]})
    return out


async def _save_message(role: str, content) -> None:
    """Save a message. Content can be a string or a rich content list."""
    if isinstance(content, str):
        stored = content
    else:
        stored = json.dumps(content, ensure_ascii=False)
    await execute(
        "INSERT INTO messages (id, role, content, created_at) VALUES (?,?,?,?)",
        (new_id(), role, stored, now_iso()),
    )


def _merge_tool_call_delta(acc: list[dict], deltas: list[dict]) -> None:
    for d in deltas:
        idx = d.get("index", 0)
        while len(acc) <= idx:
            acc.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        slot = acc[idx]
        if d.get("id"):
            slot["id"] = d["id"]
        if d.get("type"):
            slot["type"] = d["type"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]


async def _stream_llm_step(cfg: dict, messages: list[dict]) -> AsyncIterator[dict]:
    base_url = cfg.get("llm1_url", "")
    api_key  = cfg.get("llm1_api_key", "")
    model    = cfg.get("llm1_model", "")

    if not base_url or not api_key or not model:
        yield {"type": "error", "message": "LLM not configured. Open Settings to set URL, key and model."}
        return

    _b = base_url.rstrip("/")
    url = _b if _b.endswith("/chat/completions") else _b + "/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "tools": TOOL_SCHEMAS,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    content_buf: list[str] = []
    reasoning_buf: list[str] = []
    tool_calls: list[dict] = []
    finish_reason: str | None = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as cx:
            async with cx.stream("POST", url, json=payload, headers=headers) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", errors="replace")
                    yield {"type": "error", "message": f"LLM HTTP {r.status_code}: {body[:500]}"}
                    return
                async for raw in r.aiter_lines():
                    if not raw or not raw.startswith("data:"):
                        continue
                    data = raw[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    if delta.get("reasoning_content"):
                        reasoning_buf.append(delta["reasoning_content"])
                        yield {"type": "reasoning", "content": delta["reasoning_content"]}
                    if delta.get("content"):
                        content_buf.append(delta["content"])
                        yield {"type": "token", "content": delta["content"]}
                    if delta.get("tool_calls"):
                        _merge_tool_call_delta(tool_calls, delta["tool_calls"])
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
    except Exception as e:
        logger.exception("LLM stream failed")
        yield {"type": "error", "message": f"LLM stream error: {e}"}
        return

    assistant_msg: dict = {"role": "assistant"}
    content_text = "".join(content_buf)
    assistant_msg["content"] = content_text if content_text else None
    if reasoning_buf:
        assistant_msg["reasoning_content"] = "".join(reasoning_buf)
    if tool_calls:
        assistant_msg["tool_calls"] = tool_calls
    assistant_msg["_finish_reason"] = finish_reason
    yield {"type": "done", "message": assistant_msg}


async def run_agent(user_message: str) -> AsyncIterator[str]:
    """Run the agent loop. user_message is a plain text string."""
    await _save_message("user", user_message)
    yield sse({"type": "status", "status": "running"})

    cfg = await get_configs()
    system_prompt = cfg.get("system_prompt") or _load_default_prompt()

    history = await _load_history()
    messages = [{"role": "system", "content": system_prompt}] + history

    for step in range(MAX_STEPS):
        cfg = await get_configs()

        # Emit step progress
        yield sse({"type": "step", "step": step + 1, "max": MAX_STEPS})

        assistant_msg: dict | None = None
        async for ev in _stream_llm_step(cfg, messages):
            if ev["type"] == "token":
                yield sse({"type": "token", "content": ev["content"]})
            elif ev["type"] == "reasoning":
                yield sse({"type": "reasoning", "content": ev["content"]})
            elif ev["type"] == "error":
                yield sse({"type": "error", "message": ev["message"]})
                yield sse({"type": "status", "status": "error"})
                return
            elif ev["type"] == "done":
                assistant_msg = ev["message"]

        if assistant_msg is None:
            yield sse({"type": "error", "message": "LLM returned no response."})
            yield sse({"type": "status", "status": "error"})
            return

        # If the LLM wants to call tools
        tool_calls = assistant_msg.get("tool_calls") or []
        finish = assistant_msg.get("_finish_reason")

        if tool_calls:
            # Add the assistant message (with tool_calls) to context
            messages.append(assistant_msg)

            # Build rich content for storage
            content_parts: list[dict] = []
            if assistant_msg.get("content"):
                content_parts.append({"type": "text", "text": assistant_msg["content"]})

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args_str = tc["function"].get("arguments", "{}")
                tc_id = tc.get("id") or new_id()

                try:
                    fn_args = json.loads(fn_args_str)
                except json.JSONDecodeError:
                    fn_args = {}

                # Notify frontend about tool call
                yield sse({
                    "type": "tool_call",
                    "id": tc_id,
                    "name": fn_name,
                    "arguments": fn_args_str,
                })

                # Execute the tool
                result = await run_tool(fn_name, fn_args)

                # Notify frontend about tool result
                yield sse({
                    "type": "tool_result",
                    "id": tc_id,
                    "output": result,
                })

                # Add tool result to messages for LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                })

                # Save in rich content
                content_parts.append({
                    "type": "tool_call",
                    "id": tc_id,
                    "name": fn_name,
                    "arguments": fn_args_str,
                })
                content_parts.append({
                    "type": "tool_result",
                    "id": tc_id,
                    "output": result,
                })

            # Save the complete assistant turn (text + tools + results)
            await _save_message("assistant", {"content": content_parts})

            # Continue the loop — LLM will see tool results and respond
            continue

        # No tool calls — this is the final text response
        text = assistant_msg.get("content", "")
        if text:
            await _save_message("assistant", text)

        yield sse({"type": "status", "status": "done"})
        return

    # Exhausted steps
    yield sse({"type": "error", "message": f"Reached max steps ({MAX_STEPS}). Stopping."})
    yield sse({"type": "status", "status": "error"})
