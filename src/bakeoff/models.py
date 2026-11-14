"""Provider-agnostic model interface plus one adapter (Anthropic).

The harness talks to models only through `ChatModel.complete(system, content, tools)`, using the
neutral types below. Tool definitions are plain JSON Schema dicts (name, description,
input_schema). Adding another provider means writing one more adapter class.

Every request is a fresh single-turn conversation (system + one user message). The agent's
history travels as text in that message, so the harness never edits earlier turns. That keeps
the design identical across providers and avoids replaying model-specific reasoning blocks.

The API key is never handled here: the Anthropic SDK reads ANTHROPIC_API_KEY from the
environment itself. Error messages are reduced to class name and status code before they are
stored, so request headers can never end up in results.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Protocol

from .types import ToolCall, Usage

# USD per million tokens: input, output, cache read, cache write (5-minute).
# Source: Anthropic list prices as of 2026-11 (Claude API skill reference, cached 2026-11-03).
# Haiku 5.5 rates are the <=100K-token prompt card; prompts here are far smaller.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}
IMAGE_TOKEN_ESTIMATE = 1600  # deliberately above the ~1,050 a 1024x768 image costs


def cost_usd(model: str, u: Usage) -> float:
    p_in, p_out, p_cr, p_cw = PRICES[model]
    return (u.input_tokens * p_in + u.output_tokens * p_out
            + u.cache_read_tokens * p_cr + u.cache_write_tokens * p_cw) / 1_000_000


def worst_case_usd(model: str, est_input_tokens: int, max_tokens: int) -> float:
    """Upper bound for one call: every input token at the cache-write rate (the highest input
    rate) and the full output allowance used."""
    p_in, p_out, _p_cr, p_cw = PRICES[model]
    return (est_input_tokens * max(p_in, p_cw) + max_tokens * p_out) / 1_000_000


@dataclass
class Part:
    kind: str            # "text" | "image"
    text: str = ""
    png: bytes = b""


@dataclass
class ModelReply:
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    stop: str = ""
    error: str | None = None


class FatalModelError(RuntimeError):
    """Configuration problems (bad key, unknown model) that make every later call fail too."""


class ChatModel(Protocol):
    name: str
    max_tokens: int

    def complete(self, system: str, content: list[Part], tools: list[dict]) -> ModelReply: ...


def estimate_input_tokens(system: str, content: list[Part], tools: list[dict]) -> int:
    chars = len(system) + len(json.dumps(tools)) + sum(len(p.text) for p in content)
    images = sum(1 for p in content if p.kind == "image")
    return chars // 3 + images * IMAGE_TOKEN_ESTIMATE + 50


class AnthropicModel:
    def __init__(self, name: str = "claude-haiku-5-5", effort: str = "medium",
                 max_tokens: int = 4000, client=None):
        if name not in PRICES:
            raise ValueError(f"no price on file for {name}; add it to PRICES first")
        self.name, self.effort, self.max_tokens = name, effort, max_tokens
        if client is None:
            import anthropic
            client = anthropic.Anthropic(max_retries=4, timeout=120)
        self.client = client

    def _content(self, parts: list[Part]) -> list[dict]:
        out = []
        for p in parts:
            if p.kind == "image":
                out.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.standard_b64encode(p.png).decode()}})
            else:
                out.append({"type": "text", "text": p.text})
        return out

    def complete(self, system: str, content: list[Part], tools: list[dict]) -> ModelReply:
        import anthropic
        try:
            resp = self.client.messages.create(
                model=self.name,
                max_tokens=self.max_tokens,
                # Tools render before system, so this one breakpoint caches both.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                messages=[{"role": "user", "content": self._content(content)}],
                output_config={"effort": self.effort},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as e:
            raise FatalModelError(f"{type(e).__name__} (HTTP {e.status_code})") from None
        except anthropic.APIStatusError as e:
            return ModelReply(error=f"{type(e).__name__} (HTTP {e.status_code})")
        except anthropic.APIConnectionError as e:
            return ModelReply(error=type(e).__name__)

        u = resp.usage
        usage = Usage(input_tokens=u.input_tokens or 0, output_tokens=u.output_tokens or 0,
                      cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                      cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            return ModelReply(usage=usage, stop="refusal", error=f"refusal ({category})")
        calls = [ToolCall(id=b.id, name=b.name, args=dict(b.input or {}))
                 for b in resp.content if b.type == "tool_use"]
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        return ModelReply(calls=calls, text=text, usage=usage, stop=resp.stop_reason or "")


def make_model(name: str, **kw) -> ChatModel:
    if name.startswith("claude-"):
        return AnthropicModel(name, **kw)
    raise ValueError(f"no adapter for model {name}")
