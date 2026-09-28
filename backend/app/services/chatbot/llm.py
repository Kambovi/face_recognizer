"""One small interface over three kinds of language model, with tool calling.

  anthropic  Claude API          https://api.anthropic.com  (x-api-key)
  openai     OpenAI API          https://api.openai.com/v1  (Bearer key)
  ollama     local, on-premises  http://localhost:11434/v1  (OpenAI-compatible;
             use a model that supports tools, e.g. qwen2.5:7b or llama3.1:8b)

Messages are kept in one neutral format and converted per provider:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


def _base(cfg: dict[str, Any]) -> str:
    return (cfg.get("base_url") or DEFAULT_BASE.get(cfg.get("provider", ""), "")).rstrip("/")


# ------------------------------------------------------------------ anthropic
def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args})
            out.append({"role": "assistant", "content": blocks or m.get("content") or ""})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)  # several results go in one user turn
            else:
                out.append({"role": "user", "content": [block]})
    return out


async def _anthropic(cfg, system, messages, tools, client) -> LLMReply:
    body = {
        "model": cfg["model"],
        "max_tokens": int(cfg.get("max_tokens") or 1024),
        "temperature": float(cfg.get("temperature", 0.2)),
        "system": system,
        "messages": _anthropic_messages(messages),
    }
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    r = await client.post(
        f"{_base(cfg)}/v1/messages",
        json=body,
        headers={"x-api-key": cfg.get("api_key", ""), "anthropic-version": ANTHROPIC_VERSION},
    )
    if r.status_code >= 400:
        raise LLMError(f"Anthropic {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in data.get("content", []) if b.get("type") == "tool_use"]
    return LLMReply(text.strip(), calls)


# ------------------------------------------------------------------ openai / ollama
def _openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.args)}}
                    for tc in m["tool_calls"]
                ],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


async def _openai(cfg, system, messages, tools, client) -> LLMReply:
    body: dict[str, Any] = {
        "model": cfg["model"],
        "temperature": float(cfg.get("temperature", 0.2)),
        "messages": _openai_messages(system, messages),
    }
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    headers = {"Authorization": f"Bearer {cfg.get('api_key') or 'ollama'}"}
    r = await client.post(f"{_base(cfg)}/chat/completions", json=body, headers=headers)
    if r.status_code >= 400:
        raise LLMError(f"{cfg.get('provider')} {r.status_code}: {r.text[:300]}")
    msg = (r.json().get("choices") or [{}])[0].get("message") or {}
    calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except ValueError:
                args = {}
        calls.append(ToolCall(tc.get("id") or f"call_{i}", fn.get("name", ""), args))
    return LLMReply((msg.get("content") or "").strip(), calls)


async def complete(
    cfg: dict[str, Any],
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> LLMReply:
    provider = cfg.get("provider")
    if provider not in DEFAULT_BASE:
        raise LLMError("No language model configured")
    if not cfg.get("model"):
        raise LLMError("Model name is empty (Settings -> Chatbot)")
    own = client is None
    client = client or httpx.AsyncClient(timeout=float(cfg.get("timeout_seconds") or 60))
    try:
        fn = _anthropic if provider == "anthropic" else _openai
        return await fn(cfg, system, messages, tools or [], client)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach {provider} at {_base(cfg)}: {exc}") from exc
    finally:
        if own:
            await client.aclose()
