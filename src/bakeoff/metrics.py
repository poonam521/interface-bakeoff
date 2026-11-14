"""Metrics over run records. Pure functions; no I/O.

Definitions (n = runs per task that count, c = runs that passed):
  Pass^1  mean over tasks of c/n                     (ordinary per-run success)
  Pass^k  share of tasks with c == n == k             (passed in ALL k runs: the headline)
  Pass@k  share of tasks with c >= 1                  (passed at least once)
Runs that stopped for reasons outside the agent's control (harness_error, budget_stop) are
excluded. A task counts for Pass^k / Pass@k only if it has all k valid runs.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from statistics import mean

from .verify import INVALID


def valid(records: list[dict]) -> list[dict]:
    return [r for r in records if r["failure_category"] not in INVALID]


def per_task_counts(records: list[dict]) -> dict[str, tuple[int, int]]:
    """task -> (passes, valid runs)."""
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in valid(records):
        out[r["task"]][0] += r["passed"]
        out[r["task"]][1] += 1
    return {t: (c, n) for t, (c, n) in out.items()}


def pass_hat_1(counts: dict[str, tuple[int, int]]) -> float | None:
    vals = [c / n for c, n in counts.values() if n]
    return mean(vals) if vals else None


def pass_hat_k(counts: dict[str, tuple[int, int]], k: int) -> float | None:
    full = [(c, n) for c, n in counts.values() if n == k]
    return sum(c == n for c, n in full) / len(full) if full else None


def pass_at_k(counts: dict[str, tuple[int, int]], k: int) -> float | None:
    full = [(c, n) for c, n in counts.values() if n == k]
    return sum(c >= 1 for c, n in full) / len(full) if full else None


def bootstrap_ci(counts: dict[str, tuple[int, int]], stat, iters: int = 2000, seed: int = 7):
    """95% percentile interval, resampling tasks with replacement."""
    items = list(counts.values())
    if not items:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(iters):
        sample = {i: items[rng.randrange(len(items))] for i in range(len(items))}
        v = stat(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]


def summarise(records: list[dict], k: int) -> dict:
    by_iface: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_iface[r["interface"]].append(r)
    out = {}
    for iface, rs in sorted(by_iface.items()):
        v = valid(rs)
        counts = per_task_counts(rs)
        claims_done = [r for r in v if r["claim"] == "done"]
        out[iface] = {
            "runs": len(rs),
            "valid_runs": len(v),
            "excluded_runs": len(rs) - len(v),
            "tasks": len(counts),
            "tasks_with_all_k": sum(1 for _c, n in counts.values() if n == k),
            "pass_hat_1": pass_hat_1(counts),
            "pass_hat_1_ci": bootstrap_ci(counts, pass_hat_1),
            "pass_hat_k": pass_hat_k(counts, k),
            "pass_hat_k_ci": bootstrap_ci(counts, lambda c: pass_hat_k(c, k)),
            "pass_at_k": pass_at_k(counts, k),
            "mean_actions": _m(v, "actions"),
            "mean_turns": _m(v, "turns"),
            "mean_tool_errors": _m(v, "tool_errors"),
            "mean_input_tokens": _m(v, "input_tokens"),
            "mean_output_tokens": _m(v, "output_tokens"),
            "mean_cost_usd": _m(v, "cost_usd"),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rs), 6),
            "mean_wall_seconds": _m(v, "wall_seconds"),
            "failure_categories": dict(Counter(r["failure_category"] for r in rs if not r["passed"])),
            "false_success_claims": sum(r["false_success_claim"] for r in v),
            "false_success_claim_rate": (sum(r["false_success_claim"] for r in claims_done) / len(claims_done)
                                         if claims_done else None),
            "per_task": {t: list(cn) for t, cn in sorted(counts.items())},
        }
    return out


def _m(rs: list[dict], key: str) -> float | None:
    return round(mean(r[key] for r in rs), 4) if rs else None
