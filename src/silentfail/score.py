"""Score the detector against injected faults. Uses scripted tool traces only: no model, no cost.

Unit of scoring: one tool call. Ground truth: the injector's log. A flag on a clean call counts
as a false positive, except when an earlier fault in the same trace is still undetected; then it
is credited as a *delayed* detection of that earlier fault (for example, a phantom write that is
only exposed by the next read of the same ticket). Delayed detections are reported separately.
"""
from __future__ import annotations

import hashlib
import tempfile
from collections import defaultdict
from pathlib import Path

from bakeoff.app import AppServer
from bakeoff.interfaces.api import ToolLayer
from bakeoff.tasks import TASKS

from .detector import Detector
from .injector import FAULTS, FaultInjector

_WRITES = {"update_ticket", "add_comment"}


def trace_for(task) -> list[tuple[str, dict]]:
    """The task's reference API calls, with a read-back after each write (what a careful agent does)."""
    out = []
    for name, args in task.api:
        out.append((name, args))
        if name in _WRITES:
            out.append(("get_ticket", {"id": args["id"]}))
    return out


def _seed(*parts) -> int:
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _reset(app: AppServer) -> None:
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(app.base_url + "/__reset", data=b"", method="POST")).read()


def _run_trace(app, layer, task, rate, seed):
    _reset(app)
    inj = FaultInjector(layer, rate, seed=seed)
    det1 = Detector(probe=None)                                   # tier 1 only
    det2 = Detector(probe=lambda n, a: layer.call(n, a, probe=True))  # tier 1 + 2
    rows = []
    for name, args in trace_for(task):
        res = inj.call(name, dict(args))
        f1 = det1.check(name, args, res)
        f2 = det2.check(name, args, res)
        rows.append({"tool": name, "fault": inj.log[-1]["fault"], "t1": bool(f1), "t12": bool(f2),
                     "rules": sorted({f.rule for f in f2})})
    return rows, det2.probe_calls


def _tally(traces: list[list[dict]], key: str) -> dict:
    """Confusion counts for one detector configuration (`t1` or `t12`)."""
    tp = fp = fn = delayed = clean = 0
    per_fault = defaultdict(lambda: {"injected": 0, "caught": 0, "caught_delayed": 0})
    for rows in traces:
        pending: list[str] = []
        for r in rows:
            if r["fault"]:
                per_fault[r["fault"]]["injected"] += 1
                if r[key]:
                    tp += 1
                    per_fault[r["fault"]]["caught"] += 1
                else:
                    pending.append(r["fault"])
            else:
                clean += 1
                if r[key]:
                    if pending:
                        f = pending.pop(0)
                        delayed += 1
                        per_fault[f]["caught_delayed"] += 1
                    else:
                        fp += 1
        fn += len(pending)
    caught = tp + delayed
    return {
        "injected": tp + delayed + fn, "caught_same_call": tp, "caught_delayed": delayed, "missed": fn,
        "clean_calls": clean, "false_positives": fp,
        "precision": caught / (caught + fp) if caught + fp else None,
        "recall": caught / (caught + fn) if caught + fn else None,
        "recall_same_call": tp / (caught + fn) if caught + fn else None,
        "false_positive_rate": fp / clean if clean else None,
        "per_fault": {f: {**v, "recall": (v["caught"] + v["caught_delayed"]) / v["injected"] if v["injected"] else None}
                      for f, v in sorted(per_fault.items())},
    }


def score(seeds: int = 20, rate: float = 0.5) -> dict:
    with AppServer(Path(tempfile.mkdtemp()) / "sf.db") as app:
        layer = ToolLayer(app.base_url)
        faulty, probes, calls = [], 0, 0
        for s in range(seeds):
            for task in TASKS:
                rows, p = _run_trace(app, layer, task, rate, _seed(s, task.id))
                faulty.append(rows)
                probes += p
                calls += len(rows)
        clean = [_run_trace(app, layer, task, 0.0, 0)[0] for task in TASKS]
    return {
        "config": {"seeds": seeds, "injection_rate": rate, "tasks": len(TASKS), "faults": list(FAULTS)},
        "tier1_invariants": _tally(faulty, "t1"),
        "tier1_plus_crosschecks": _tally(faulty, "t12"),
        "clean_traces": {"calls": sum(len(r) for r in clean),
                         "flagged_tier1": sum(r["t1"] for rows in clean for r in rows),
                         "flagged_tier1_plus_2": sum(r["t12"] for rows in clean for r in rows)},
        "crosscheck_overhead": {"agent_calls": calls, "probe_calls": probes,
                                "probes_per_call": round(probes / calls, 2) if calls else None},
    }


def to_markdown(res: dict) -> str:
    c = res["config"]
    lines = [
        "# silentfail: detector precision and recall",
        "",
        f"Scripted API traces for all {c['tasks']} tasks (reference solution plus a read-back after each write), "
        f"{c['seeds']} seeds, injection rate {c['injection_rate']} per eligible call. No model calls.",
        "",
        "| Detector | Injected | Caught (same call) | Caught (later call) | Missed | False positives | Precision | Recall |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label, key in (("Tier 1: invariants", "tier1_invariants"), ("Tier 1 + 2: cross-checks", "tier1_plus_crosschecks")):
        t = res[key]
        lines.append(f"| {label} | {t['injected']} | {t['caught_same_call']} | {t['caught_delayed']} | {t['missed']} | "
                     f"{t['false_positives']} of {t['clean_calls']} clean | {_p(t['precision'])} | {_p(t['recall'])} |")
    lines += ["", "Recall by fault type:", "", "| Fault | Injected | Tier 1 | Tier 1 + 2 |", "|---|---|---|---|"]
    t1, t12 = res["tier1_invariants"]["per_fault"], res["tier1_plus_crosschecks"]["per_fault"]
    for f in sorted(t12):
        lines.append(f"| `{f}` | {t12[f]['injected']} | {_p(t1.get(f, {}).get('recall'))} | {_p(t12[f]['recall'])} |")
    cl, ov = res["clean_traces"], res["crosscheck_overhead"]
    lines += ["", f"Clean traces (no injection): {cl['calls']} calls, {cl['flagged_tier1']} flagged by tier 1, "
                  f"{cl['flagged_tier1_plus_2']} by tier 1 + 2.",
              f"Cross-check cost: {ov['probe_calls']} extra API calls for {ov['agent_calls']} agent calls "
              f"({ov['probes_per_call']} per call).", ""]
    return "\n".join(lines)


def _p(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"
