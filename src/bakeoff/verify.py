"""State-based verification. Works on database snapshots only; never reads agent text."""
from __future__ import annotations

from dataclasses import dataclass, field

from .app.db import VOLATILE
from .tasks import Task

Snapshot = dict[str, dict[int, dict]]


@dataclass
class Diff:
    inserts: list[tuple[str, dict]] = field(default_factory=list)
    deletes: list[tuple[str, int]] = field(default_factory=list)
    updates: dict[tuple[str, int], dict[str, tuple]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.inserts or self.deletes or self.updates)

    def describe(self) -> list[str]:
        out = [f"insert {t} #{r['id']}" for t, r in self.inserts]
        out += [f"delete {t} #{i}" for t, i in self.deletes]
        for (t, i), cols in self.updates.items():
            out += [f"update {t} #{i}.{c}: {old!r} -> {new!r}" for c, (old, new) in cols.items()]
        return out


def diff(before: Snapshot, after: Snapshot) -> Diff:
    d = Diff()
    for table in before:
        b, a = before[table], after.get(table, {})
        for rid in a.keys() - b.keys():
            d.inserts.append((table, a[rid]))
        for rid in b.keys() - a.keys():
            d.deletes.append((table, rid))
        for rid in b.keys() & a.keys():
            cols = {c: (b[rid][c], a[rid][c]) for c in b[rid]
                    if c not in VOLATILE and b[rid][c] != a[rid][c]}
            if cols:
                d.updates[(table, rid)] = cols
    d.inserts.sort(key=lambda x: (x[0], x[1]["id"]))
    d.deletes.sort()
    return d


def _same(expected, actual) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()
    return expected == actual


@dataclass
class Verdict:
    target_met: bool
    missing: list[str]        # expected changes that are absent
    collateral: list[str]     # changes that were not asked for
    changed: bool             # did the database change at all

    @property
    def state_ok(self) -> bool:
        return self.target_met and not self.collateral


def judge(task: Task, seed: Snapshot, final: Snapshot) -> Verdict:
    d = diff(seed, final)
    missing: list[str] = []
    collateral: list[str] = []

    for key, want in task.updates.items():
        row = final.get(key[0], {}).get(key[1])
        for col, val in want.items():
            if row is None or not _same(val, row[col]):
                got = "row deleted" if row is None else repr(row[col])
                missing.append(f"{key[0]} #{key[1]}.{col} should be {val!r}, is {got}")
    for key, cols in d.updates.items():
        for col, (old, new) in cols.items():
            if col not in task.updates.get(key, {}):
                collateral.append(f"update {key[0]} #{key[1]}.{col}: {old!r} -> {new!r}")

    unmatched = list(d.inserts)
    for table, want in task.inserts:
        hit = next((x for x in unmatched if x[0] == table
                    and all(_same(v, x[1].get(c)) for c, v in want.items())), None)
        if hit is None:
            missing.append(f"no new {table} row matching {want}")
        else:
            unmatched.remove(hit)
    collateral += [f"insert {t} #{r['id']}: {_brief(r)}" for t, r in unmatched]

    for key in task.deletes:
        if key not in d.deletes:
            missing.append(f"{key[0]} #{key[1]} should be deleted")
    collateral += [f"delete {t} #{i}" for t, i in d.deletes if (t, i) not in task.deletes]

    return Verdict(target_met=not missing, missing=missing, collateral=collateral, changed=not d.empty)


def _brief(row: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in row.items() if k not in VOLATILE and k != "id")[:160]


def label_step(task: Task, before: Snapshot, after: Snapshot) -> tuple[str, list[str]]:
    """Step-level postcondition: did this one action change only things the task is about?"""
    d = diff(before, after)
    if d.empty:
        return "no_change", []
    ok = True
    for key, cols in d.updates.items():
        ok &= all(c in task.updates.get(key, {}) for c in cols)
    insert_tables = {t for t, _ in task.inserts}
    ok &= all(t in insert_tables for t, _ in d.inserts)
    ok &= all(k in task.deletes for k in d.deletes)
    return ("in_scope" if ok else "out_of_scope"), d.describe()


INVALID = ("harness_error", "budget_stop")   # not the agent's doing; excluded from metrics


def classify(task: Task, verdict: Verdict, claim: str | None, stop: str) -> tuple[bool, str | None]:
    """Return (passed, failure_category). `stop` is how the loop ended:
    finish | no_action | step_limit | model_error | budget_stop | harness_error."""
    if stop in INVALID:
        return False, stop
    passed = verdict.state_ok and (task.feasible or claim == "impossible")
    if passed:
        return True, None
    if stop == "model_error":
        return False, "model_error"
    if stop == "step_limit":
        return False, "step_limit"
    if verdict.target_met and verdict.collateral:
        return False, "collateral_damage"
    if not task.feasible:
        return False, "wrong_claim_infeasible"
    if not verdict.changed:
        return False, "gave_up" if claim == "impossible" else "no_effect"
    return False, "wrong_target"
