"""Interface contract: every interface is a list of function tools plus a way to run them."""
from __future__ import annotations

from typing import Protocol

from ..types import Observation

FINISH_TOOL = {
    "name": "finish",
    "description": (
        "End the task. Use outcome 'done' when the task has been carried out. Use outcome "
        "'impossible' when the task cannot be carried out as stated; in that case change nothing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["done", "impossible"]},
            "note": {"type": "string", "description": "One short sentence."},
        },
        "required": ["outcome"],
        "additionalProperties": False,
    },
}


def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "required": required,
                         "additionalProperties": False},
    }


class Interface(Protocol):
    name: str
    guidance: str           # interface-specific paragraph for the system prompt

    def tools(self) -> list[dict]: ...
    def start(self) -> Observation: ...
    def act(self, name: str, args: dict) -> Observation: ...
    def close(self) -> None: ...
