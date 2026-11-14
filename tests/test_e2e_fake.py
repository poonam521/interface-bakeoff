"""End to end with the scripted fake agent: real app, real browser, real verifier, no model."""
import json
import os

import pytest

from bakeoff.agents import _unit
from bakeoff.cli import main
from bakeoff.harness import ALL_TASK_IDS, run_matrix
from bakeoff.metrics import summarise

IFACES = ["screenshot", "a11y", "api"]


@pytest.fixture(scope="module")
def perfect(tmp_path_factory):
    out = tmp_path_factory.mktemp("perfect")
    records, stop = run_matrix(ALL_TASK_IDS, IFACES, 2, {"agent": "fake", "mode": "perfect"}, out)
    return out, records, stop


def test_perfect_agent_passes_everything(perfect):
    out, records, stop = perfect
    assert stop is None and len(records) == len(ALL_TASK_IDS) * 3 * 2
    failed = [(r["task"], r["interface"], r["failure_category"], r["error"]) for r in records if not r["passed"]]
    assert failed == []
    s = summarise(records, 2)
    assert all(s[i]["pass_hat_k"] == 1.0 for i in IFACES)
    assert all(r["first_out_of_scope_step"] is None for r in records)


def test_every_step_is_recorded(perfect):
    out, records, _ = perfect
    traj = json.loads((out / "trajectories" / "escalate__a11y__0.json").read_text())
    labels = [s["label"] for s in traj["steps"]]
    assert "in_scope" in labels and "out_of_scope" not in labels
    assert (out / "manifest.json").exists() and (out / "runs.jsonl").exists()


def test_liar_is_caught_by_state(tmp_path):
    tasks = ["close_by_title", "create_basic", "close_missing_ticket"]
    records, _ = run_matrix(tasks, ["api", "a11y"], 1, {"agent": "fake", "mode": "liar"}, tmp_path)
    assert not any(r["passed"] for r in records)
    assert all(r["false_success_claim"] for r in records)
    cats = {(r["task"], r["failure_category"]) for r in records}
    assert ("close_by_title", "no_effect") in cats and ("close_missing_ticket", "wrong_claim_infeasible") in cats


def test_clumsy_is_collateral_damage_on_every_interface(tmp_path):
    records, _ = run_matrix(["close_by_title", "add_comment"], IFACES, 1,
                            {"agent": "fake", "mode": "clumsy"}, tmp_path)
    assert {r["failure_category"] for r in records} == {"collateral_damage"}
    assert all(r["first_out_of_scope_step"] is not None for r in records)


def test_flaky_matches_the_seeded_schedule(tmp_path):
    tasks, k, rate = ALL_TASK_IDS[:6], 4, 0.3
    records, _ = run_matrix(tasks, ["api"], k, {"agent": "fake", "mode": "flaky", "fail_rate": rate, "seed": 5},
                            tmp_path)
    expected_pass = {(t, r): _unit(5, t, "api", r) >= rate for t in tasks for r in range(k)}
    assert {(r["task"], r["run"]): r["passed"] for r in records} == expected_pass
    s = summarise(records, k)["api"]
    want_k = sum(all(expected_pass[(t, r)] for r in range(k)) for t in tasks) / len(tasks)
    assert s["pass_hat_k"] == pytest.approx(want_k)


def test_cli_run_and_report(tmp_path, capsys):
    assert main(["run", "--tasks", "close_by_title,escalate", "--interfaces", "api", "-k", "2",
                 "--out", str(tmp_path), "--name", "cli"]) == 0
    assert (tmp_path / "cli" / "report.md").exists()
    assert main(["report", str(tmp_path / "cli")]) == 0


def test_cli_refuses_real_run_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--agent", "model", "--tasks", "close_by_title", "--interfaces", "api", "-k", "1"]) == 2
    assert "not set" in capsys.readouterr().out
    assert not (tmp_path / "results" / "spend_ledger.json").exists() or \
        json.loads((tmp_path / "results" / "spend_ledger.json").read_text())["spent_usd"] == 0


def test_cli_cap_cannot_exceed_hard_cap():
    with pytest.raises(SystemExit):
        main(["run", "--cap", "10.01", "--dry-run"])


def test_no_key_material_in_outputs(tmp_path, monkeypatch):
    sentinel = "sk-ant-TESTSENTINEL-0123456789"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    run_matrix(["close_by_title"], ["api"], 1, {"agent": "fake", "mode": "perfect"}, tmp_path)
    for root, _dirs, files in os.walk(tmp_path):
        for f in files:
            assert sentinel not in open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
