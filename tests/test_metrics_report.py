import json

import pytest

from bakeoff.metrics import pass_at_k, pass_hat_1, pass_hat_k, per_task_counts, summarise
from bakeoff.report import build


def rec(task, iface, run, passed, cat=None, claim="done", cost=0.01):
    return {"task": task, "category": "edit", "interface": iface, "run": run, "passed": passed,
            "failure_category": None if passed else (cat or "no_effect"), "stop": "finish", "claim": claim,
            "false_success_claim": claim == "done" and not passed, "turns": 3, "actions": 2,
            "tool_errors": 0, "first_out_of_scope_step": None, "input_tokens": 100, "output_tokens": 10,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": cost, "wall_seconds": 1.0,
            "missing": [], "collateral": [], "error": None}


# Task a passes 3/3, task b 2/3, task c 0/3, all on one interface.
RECORDS = ([rec("close_by_title", "api", r, True) for r in range(3)]
           + [rec("escalate", "api", r, r != 1) for r in range(3)]
           + [rec("add_comment", "api", r, False) for r in range(3)])


def test_hand_computed_metrics():
    counts = per_task_counts(RECORDS)
    assert pass_hat_1(counts) == pytest.approx((1 + 2 / 3 + 0) / 3)
    assert pass_hat_k(counts, 3) == pytest.approx(1 / 3)
    assert pass_at_k(counts, 3) == pytest.approx(2 / 3)


def test_invalid_runs_are_excluded_and_tasks_marked_incomplete():
    rs = RECORDS + [rec("fix_title_typo", "api", 0, False, cat="harness_error")]
    s = summarise(rs, 3)["api"]
    assert s["excluded_runs"] == 1 and s["tasks_with_all_k"] == 3
    assert s["pass_hat_k"] == pytest.approx(1 / 3)
    assert s["false_success_claims"] == 4
    assert s["failure_categories"] == {"no_effect": 4, "harness_error": 1}
    lo, hi = s["pass_hat_k_ci"]
    assert 0 <= lo <= s["pass_hat_k"] <= hi <= 1


def test_report_files(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "started": "s", "ended": "e", "agent": {"agent": "fake", "mode": "perfect"},
        "tasks": ["close_by_title", "escalate", "add_comment"], "interfaces": ["api"], "k": 3,
        "runs_recorded": 9, "runs_planned": 9, "stop_reason": None, "git_commit": None}))
    with open(tmp_path / "runs.jsonl", "w") as f:
        for r in RECORDS:
            f.write(json.dumps(r) + "\n")
    report = build(tmp_path)
    md = (tmp_path / "report.md").read_text()
    assert "| api | **33%**" in md and "| `escalate` | multi_step | 2/3 |" in md
    assert (tmp_path / "chart.png").read_bytes()[:4] == b"\x89PNG"
    assert report["total_cost_usd"] == pytest.approx(0.09)
