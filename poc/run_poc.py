"""Proof of concept: one app, one task, one interface, one state-based check.

    python poc/run_poc.py            # real model (needs ANTHROPIC_API_KEY)
    python poc/run_poc.py --scripted # no key: a scripted stand-in for the model

The verdict comes from reading the SQLite file directly. The agent's final
message is printed but never used to decide pass or fail.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).parent))
from app import SEED, create_app, reset_db  # noqa: E402

TASK = (
    "In the ticket tracker, close the ticket titled 'Printer on floor 2 is jammed' "
    "and assign it to Dana. Use the tools. Say DONE when finished."
)
MAX_STEPS = 8

TOOLS = [
    {
        "name": "list_tickets",
        "description": "List all tickets with id, title, status, assignee and priority.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "update_ticket",
        "description": "Update fields of one ticket. Status is open, in_progress or closed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "status": {"type": "string", "enum": ["open", "in_progress", "closed"]},
                "assignee": {"type": "string"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def http(method: str, url: str, body: dict | None = None) -> str:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()


def execute_tool(base: str, name: str, args: dict) -> str:
    if name == "list_tickets":
        return http("GET", f"{base}/api/tickets")
    if name == "update_ticket":
        args = dict(args)
        tid = args.pop("id")
        return http("PATCH", f"{base}/api/tickets/{tid}", args)
    return json.dumps({"error": f"unknown tool {name}"})


class ScriptedModel:
    """Stands in for the model when there is no API key. Fixed, deterministic."""

    def __init__(self):
        self.turn = 0

    def create(self, **_kw):
        self.turn += 1
        use = lambda name, inp: SimpleNamespace(  # noqa: E731
            type="tool_use", id=f"t{self.turn}", name=name, input=inp)
        if self.turn == 1:
            content, stop = [use("list_tickets", {})], "tool_use"
        elif self.turn == 2:
            content, stop = [use("update_ticket",
                                 {"id": 1, "status": "closed", "assignee": "Dana"})], "tool_use"
        else:
            content, stop = [SimpleNamespace(type="text", text="DONE")], "end_turn"
        return SimpleNamespace(content=content, stop_reason=stop,
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0))


def run_agent(base: str, model_name: str, scripted: bool) -> tuple[str, int, int, int]:
    if scripted:
        create = ScriptedModel().create
    else:
        import anthropic  # the key is read from the environment by the SDK
        create = anthropic.Anthropic().messages.create

    messages = [{"role": "user", "content": TASK}]
    steps = tokens_in = tokens_out = 0
    final = ""
    while steps < MAX_STEPS:
        resp = create(model=model_name, max_tokens=2000, tools=TOOLS, messages=messages)
        steps += 1
        tokens_in += resp.usage.input_tokens
        tokens_out += resp.usage.output_tokens
        final = " ".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = execute_tool(base, block.name, block.input)
                print(f"  step {steps}: {block.name}({json.dumps(block.input)})")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
        messages.append({"role": "user", "content": results})
    return final, steps, tokens_in, tokens_out


def check_state(db_path: Path) -> tuple[bool, list[str]]:
    """Pass only if ticket 1 is closed and assigned to Dana AND nothing else changed."""
    con = sqlite3.connect(db_path)
    rows = {r[0]: r for r in con.execute("SELECT * FROM tickets ORDER BY id")}
    con.close()
    problems = []
    target = rows.get(1)
    if target is None or target[2] != "closed":
        problems.append(f"ticket 1 status is {target[2] if target else 'missing'}, expected closed")
    if target is None or target[3] != "Dana":
        problems.append(f"ticket 1 assignee is {target[3] if target else 'missing'}, expected Dana")
    for seed in SEED[1:]:
        if rows.get(seed[0]) != seed:
            problems.append(f"ticket {seed[0]} changed but should not have: {rows.get(seed[0])}")
    if len(rows) != len(SEED):
        problems.append(f"expected {len(SEED)} tickets, found {len(rows)}")
    return (not problems), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripted", action="store_true", help="no API call; scripted stand-in")
    ap.add_argument("--model", default="claude-opus-5-5")
    args = ap.parse_args()

    if not args.scripted and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Set it, or run with --scripted.")
        return 2

    db_path = Path(tempfile.mkdtemp()) / "poc.db"
    reset_db(db_path)
    server = make_server("127.0.0.1", 0, create_app(db_path))
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        http("POST", f"{base}/reset")
        print(f"app:   {base}  (db: {db_path})")
        print(f"agent: {'scripted stand-in' if args.scripted else args.model}")
        print(f"task:  {TASK}")
        final, steps, tin, tout = run_agent(base, args.model, args.scripted)
        ok, problems = check_state(db_path)
        print(f"agent said: {final!r}  (not used for the verdict)")
        print(f"steps={steps} input_tokens={tin} output_tokens={tout}")
        print("STATE CHECK:", "PASS" if ok else "FAIL")
        for p in problems:
            print("  -", p)
        return 0 if ok else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
