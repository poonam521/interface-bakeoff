"""Small shared data types. Nothing here knows about any model provider."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Observation:
    """What an interface returns after an action.

    summary: short text that goes into the action history (for the API interface this is the
             whole JSON result, because that result is the only thing the agent ever sees).
    view:    the current page as text (a11y interface only).
    image:   PNG bytes of the current page (screenshot interface only).
    """
    summary: str
    view: str = ""
    image: bytes | None = None
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens


@dataclass
class Step:
    index: int
    name: str
    args: dict[str, Any]
    summary: str
    is_error: bool
    label: str = "no_change"          # no_change | in_scope | out_of_scope
    changes: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """What an agent wants to do next."""
    calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    text: str = ""
    error: str | None = None          # set when the model call failed or was refused
    budget_stop: bool = False
