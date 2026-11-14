"""Detector for silent tool faults.

Tier 1 (free): invariants on one response and on what this run has already seen.
Tier 2 (costs extra calls): cross-checks through another route of the same API. Never reads the
database directly: a real deployment has no oracle, only the API.
"""
from __future__ import annotations

from dataclasses import dataclass

from bakeoff.app.db import PRIORITIES, STATUSES, USERS

_FIELDS = ("title", "description", "status", "priority", "assignee", "due_date", "updated_at")
_REQUIRED = {"id", "title", "description", "status", "priority", "assignee", "due_date", "created_at", "updated_at"}


@dataclass
class Finding:
    tier: int
    rule: str
    detail: str


def _norm(field: str, v):
    if field in ("assignee", "due_date") and v == "":
        return None
    return v.strip() if isinstance(v, str) else v


def _matches(t: dict, args: dict) -> bool:
    for f in ("status", "assignee", "priority"):
        if args.get(f) and t.get(f) != args[f]:
            return False
    q = (args.get("q") or "").lower()
    return not q or q in (t.get("title") or "").lower() or q in (t.get("description") or "").lower()


class Detector:
    def __init__(self, probe=None, tiers: tuple[int, ...] = (1, 2)):
        self.probe = probe          # callable(name, args) -> result, never faulted
        self.tiers = tiers if probe else (1,)
        self.latest: dict[int, str] = {}   # ticket id -> newest updated_at seen in this run
        self.probe_calls = 0

    def _p(self, name, args):
        self.probe_calls += 1
        return self.probe(name, args)

    # ------------------------------------------------------------------ tier 1
    def _schema(self, t: dict, where: str) -> list[Finding]:
        out = []
        missing = _REQUIRED - t.keys()
        if missing:
            out.append(Finding(1, "schema", f"{where}: missing {sorted(missing)}"))
        if t.get("status") not in STATUSES:
            out.append(Finding(1, "enum", f"{where}: status {t.get('status')!r}"))
        if t.get("priority") not in PRIORITIES:
            out.append(Finding(1, "enum", f"{where}: priority {t.get('priority')!r}"))
        if t.get("assignee") not in (None, *USERS):
            out.append(Finding(1, "enum", f"{where}: assignee {t.get('assignee')!r}"))
        return out

    def _monotonic(self, t: dict, where: str) -> list[Finding]:
        tid, ts = t.get("id"), t.get("updated_at")
        if tid is None or not ts:
            return []
        seen = self.latest.get(tid)
        if seen and ts < seen:
            return [Finding(1, "time_went_backwards", f"{where}: ticket {tid} updated_at {ts} < {seen}")]
        return []

    def _remember(self, name: str, r: dict) -> None:
        """Only results that passed every check update what the detector believes."""
        rows = r.get("tickets", []) if name == "search_tickets" else [r]
        for t in rows:
            tid, ts = t.get("id"), t.get("updated_at")
            if tid is not None and ts:
                self.latest[tid] = max(ts, self.latest.get(tid, ts))

    def _tier1(self, name: str, args: dict, r: dict) -> list[Finding]:
        out: list[Finding] = []
        if name in ("get_ticket", "update_ticket", "create_ticket"):
            out += self._schema(r, name)
            if name != "create_ticket" and r.get("id") != args.get("id"):
                out.append(Finding(1, "id_mismatch", f"asked for {args.get('id')}, got {r.get('id')}"))
            for c in r.get("comments", []):
                if c.get("ticket_id") != r.get("id"):
                    out.append(Finding(1, "comment_owner", f"comment {c.get('id')} belongs to {c.get('ticket_id')}"))
            if name == "update_ticket":
                for f, v in args.items():
                    if f != "id" and _norm(f, r.get(f)) != _norm(f, v):
                        out.append(Finding(1, "echo_mismatch", f"{f}: sent {v!r}, got {r.get(f)!r}"))
            out += self._monotonic(r, name)
        elif name == "search_tickets":
            rows = r.get("tickets", [])
            if r.get("total") != len(rows):
                out.append(Finding(1, "count_mismatch", f"total {r.get('total')} but {len(rows)} rows"))
            for t in rows:
                out += self._schema(t, f"row {t.get('id')}")
                if not _matches(t, args):
                    out.append(Finding(1, "filter_violation", f"row {t.get('id')} does not match {args}"))
                out += self._monotonic(t, f"row {t.get('id')}")
        return out

    # ------------------------------------------------------------------ tier 2
    def _same(self, a: dict, b: dict) -> list[str]:
        return [f for f in _FIELDS if a.get(f) != b.get(f)]

    def _tier2(self, name: str, args: dict, r: dict) -> list[Finding]:
        out: list[Finding] = []
        if name in ("get_ticket", "update_ticket", "create_ticket"):
            fresh = self._p("get_ticket", {"id": r.get("id")})
            if "error" in fresh:
                out.append(Finding(2, "readback_missing", f"ticket {r.get('id')} not found on re-read"))
            else:
                diff = self._same(r, fresh)
                if diff:
                    out.append(Finding(2, "readback_differs", f"ticket {r.get('id')}: {diff}"))
                if name == "get_ticket" and len(fresh.get("comments", [])) != len(r.get("comments", [])):
                    out.append(Finding(2, "readback_differs", f"ticket {r.get('id')}: comment count"))
        elif name == "search_tickets":
            rows = r.get("tickets", [])
            everything = self._p("search_tickets", {}).get("tickets", [])
            expected = {t["id"] for t in everything if _matches(t, args)}
            got = {t["id"] for t in rows}
            if expected != got:
                out.append(Finding(2, "result_set_differs",
                                   f"missing {sorted(expected - got)}, extra {sorted(got - expected)}"))
            by_id = {t["id"]: t for t in everything}
            for t in rows:
                if t["id"] in by_id and self._same(t, by_id[t["id"]]):
                    out.append(Finding(2, "row_differs", f"row {t['id']}: {self._same(t, by_id[t['id']])}"))
        return out

    def check(self, name: str, args: dict, result) -> list[Finding]:
        if not isinstance(result, dict) or "error" in result:
            return []   # an explicit error is not a silent failure
        findings = self._tier1(name, args, result)
        if 2 in self.tiers:
            findings += self._tier2(name, args, result)
        if not findings:
            self._remember(name, result)
        return findings
