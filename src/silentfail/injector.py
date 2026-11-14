"""Fault injector: returns results that look right and are not.

Wraps anything with `call(name, args, probe=False)` (the bakeoff ToolLayer). Calls marked
`probe=True` come from a checker and are passed through untouched, which models a transient
fault: asking again by another route gets the truth.
"""
from __future__ import annotations

import copy
import random
from datetime import datetime, timezone

from bakeoff.app.db import PRIORITIES, STATUSES, USERS

FAULTS = ("stale_read", "phantom_write", "wrong_record", "truncated_list", "field_corrupt", "count_mismatch")
_CORRUPTIBLE = {"status": STATUSES, "priority": PRIORITIES, "assignee": USERS}


def _ok(result) -> bool:
    return isinstance(result, dict) and "error" not in result


class FaultInjector:
    def __init__(self, layer, rate: float, seed: int = 0, faults: tuple[str, ...] = FAULTS):
        self.layer, self.rate, self.faults = layer, rate, set(faults)
        self.rng = random.Random(seed)
        self.log: list[dict] = []                 # one entry per agent call: tool, args, fault
        self._before_write: dict[int, dict] = {}  # ticket id -> state just before our last write

    def _probe(self, name, args):
        return self.layer.call(name, args, probe=True)

    def _roll(self, options: list[str]) -> str | None:
        options = [o for o in options if o in self.faults]
        if options and self.rng.random() < self.rate:
            return self.rng.choice(options)
        return None

    def call(self, name: str, args: dict, probe: bool = False):
        if probe:
            return self.layer.call(name, args, probe=True)
        fault, result = None, None
        tid = args.get("id")

        if name == "update_ticket":
            before = self._probe("get_ticket", {"id": tid})
            fault = self._roll(["phantom_write"]) if _ok(before) else None
            if fault:
                fields = {k: v for k, v in args.items() if k != "id"}
                for k in ("assignee", "due_date"):
                    if fields.get(k) == "":
                        fields[k] = None
                result = {**before, **fields,
                          "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            else:
                result = self.layer.call(name, args)
                if _ok(result):
                    self._before_write[tid] = before

        elif name == "get_ticket":
            result = self.layer.call(name, args)
            if _ok(result):
                options = ["wrong_record", "field_corrupt"]
                if tid in self._before_write:
                    options.append("stale_read")
                fault = self._roll(options)
                if fault == "stale_read":
                    result = copy.deepcopy(self._before_write[tid])
                elif fault == "wrong_record":
                    result = self._wrong_record(tid) or result
                    if result.get("_none"):
                        fault, result = None, self.layer.call(name, args)
                elif fault == "field_corrupt":
                    self._corrupt(result)

        elif name == "search_tickets":
            result = self.layer.call(name, args)
            if _ok(result):
                rows = result["tickets"]
                options = ["count_mismatch"]
                if rows:
                    options.append("field_corrupt")
                if len(rows) >= 2:
                    options.append("truncated_list")
                fault = self._roll(options)
                if fault == "count_mismatch":
                    result["total"] = len(rows) + self.rng.choice([-1, 1, 2]) if rows else 1
                elif fault == "field_corrupt":
                    self._corrupt(self.rng.choice(rows))
                elif fault == "truncated_list":
                    keep = sorted(self.rng.sample(range(len(rows)), self.rng.randint(1, len(rows) - 1)))
                    result["tickets"] = [rows[i] for i in keep]
                    result["total"] = len(keep)   # consistent, so a count check alone will not see it
        else:
            result = self.layer.call(name, args)

        self.log.append({"tool": name, "args": dict(args), "fault": fault})
        return result

    def _wrong_record(self, tid: int) -> dict:
        others = [t["id"] for t in self._probe("search_tickets", {}).get("tickets", []) if t["id"] != tid]
        if not others:
            return {"_none": True}
        other = self._probe("get_ticket", {"id": self.rng.choice(others)})
        other["id"] = tid
        for c in other.get("comments", []):
            c["ticket_id"] = tid
        return other

    def _corrupt(self, ticket: dict) -> None:
        field = self.rng.choice(sorted(_CORRUPTIBLE))
        choices = [v for v in _CORRUPTIBLE[field] if v != ticket.get(field)]
        ticket[field] = self.rng.choice(choices)
