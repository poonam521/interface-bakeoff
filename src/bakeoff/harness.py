"""The run loop: reset, act, check every step, verify the final state, write one record."""
from __future__ import annotations

import json
import multiprocessing as mp
import subprocess
import tempfile
import time
import traceback
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from silentfail import claim_check

from .agents import FakeAgent, ModelAgent
from .app import AppServer, reset_db, snapshot, state_hash
from .budget import BudgetGuard
from .interfaces import make_interface
from .models import FatalModelError, make_model
from .tasks import TASKS, BY_ID, Task
from .types import Step, Usage
from .verify import classify, judge, label_step

MAX_TURNS = 20


def seed_snapshot() -> tuple[dict, str]:
    path = Path(tempfile.mkdtemp()) / "seed.db"
    reset_db(path)
    snap = snapshot(path)
    return snap, state_hash(snap)


@dataclass
class Job:
    task_id: str
    interface: str
    run_index: int


def make_agent(cfg: dict):
    if cfg["agent"] == "fake":
        return FakeAgent(cfg.get("mode", "perfect"), cfg.get("fail_rate", 0.3), cfg.get("seed", 0))
    model = make_model(cfg["model"], effort=cfg.get("effort", "medium"), max_tokens=cfg.get("max_tokens", 4000))
    return ModelAgent(model, BudgetGuard(cfg["ledger"], cfg.get("cap", 10.0)))


class Runner:
    """Owns one app process, one database file and (if needed) one browser."""

    def __init__(self, interfaces: set[str]):
        self.db = Path(tempfile.mkdtemp()) / "app.db"
        self.app = AppServer(self.db).start()
        self.seed, self.seed_hash = seed_snapshot()
        self._pw = self.browser = None
        if interfaces & {"a11y", "screenshot"}:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self.browser = self._pw.chromium.launch()

    def close(self) -> None:
        if self.browser:
            self.browser.close()
            self._pw.stop()
        self.app.stop()

    def reset(self) -> None:
        req = urllib.request.Request(self.app.base_url + "/__reset", method="POST", data=b"")
        urllib.request.urlopen(req, timeout=10).read()

    def run(self, task: Task, iface_name: str, run_index: int, agent, max_turns: int = MAX_TURNS,
            layer=None) -> tuple[dict, dict]:
        """Returns (record, trajectory)."""
        t0 = time.monotonic()
        usage, cost, steps = Usage(), 0.0, []
        turns = tool_errors = 0
        claim = error = None
        stop = ""
        iface = None
        try:
            self.reset()
            if state_hash(snapshot(self.db)) != self.seed_hash:
                raise RuntimeError("database did not match the seed after reset")
            iface = make_interface(iface_name, self.app.base_url, self.browser, layer)
            agent.begin(task, iface, iface.start(), run_index=run_index)
            while not stop:
                if turns >= max_turns:
                    stop = "step_limit"
                    break
                d = agent.next()
                turns += 1
                usage.add(d.usage)
                cost += d.cost_usd
                if d.budget_stop:
                    stop, error = "budget_stop", d.error
                    break
                if d.error:
                    stop, error = "model_error", d.error
                    break
                if not d.calls:
                    stop = "no_action"
                    break
                for call in d.calls:
                    if call.name == "finish":
                        claim, stop = call.args.get("outcome"), "finish"
                        break
                    before = snapshot(self.db)
                    obs = iface.act(call.name, call.args)
                    label, changes = label_step(task, before, snapshot(self.db))
                    tool_errors += obs.is_error
                    steps.append(Step(len(steps) + 1, call.name, call.args, obs.summary[:2000],
                                      obs.is_error, label, changes))
                    agent.observe(call, obs)
        except FatalModelError:
            raise
        except Exception as e:  # noqa: BLE001 - any harness fault is recorded, never blamed on the agent
            stop, error = "harness_error", f"{type(e).__name__}: {e}"[:500]
            traceback.print_exc()
        finally:
            if iface is not None:
                try:
                    iface.close()
                except Exception:  # noqa: BLE001
                    pass

        verdict = judge(task, self.seed, snapshot(self.db))
        passed, category = classify(task, verdict, claim, stop)
        out_of_scope = next((s.index for s in steps if s.label == "out_of_scope"), None)
        record = {
            "task": task.id, "category": task.category, "interface": iface_name, "run": run_index,
            "passed": passed, "failure_category": category, "stop": stop, "claim": claim,
            "false_success_claim": claim_check(claim, passed),
            "turns": turns, "actions": len(steps), "tool_errors": tool_errors,
            "first_out_of_scope_step": out_of_scope,
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens, "cache_write_tokens": usage.cache_write_tokens,
            "cost_usd": round(cost, 6), "wall_seconds": round(time.monotonic() - t0, 2),
            "missing": verdict.missing, "collateral": verdict.collateral, "error": error,
        }
        trajectory = {**{k: record[k] for k in ("task", "interface", "run", "passed", "failure_category",
                                                 "claim", "stop")},
                      "instruction": task.instruction, "steps": [asdict(s) for s in steps]}
        return record, trajectory


def _worker(args) -> list[dict]:
    jobs, cfg, out_dir = args
    out = Path(out_dir)
    stop_flag = out / "STOP"
    runner = Runner({j.interface for j in jobs})
    records = []
    try:
        for j in jobs:
            if stop_flag.exists():
                break
            agent = make_agent(cfg)
            try:
                rec, traj = runner.run(BY_ID[j.task_id], j.interface, j.run_index, agent)
            except FatalModelError as e:
                stop_flag.write_text(f"fatal model error: {e}")
                break
            records.append(rec)
            (out / "trajectories" / f"{j.task_id}__{j.interface}__{j.run_index}.json").write_text(
                json.dumps(traj, indent=1, ensure_ascii=False))
            print(f"[{j.interface:10}] {j.task_id:26} run {j.run_index}: "
                  f"{'PASS' if rec['passed'] else 'FAIL ' + str(rec['failure_category'])}"
                  f"  ${rec['cost_usd']:.4f}", flush=True)
            if rec["stop"] == "budget_stop":
                stop_flag.write_text(f"budget stop: {rec['error']}")
                break
    finally:
        runner.close()
    return records


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=5, cwd=Path(__file__).parent).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def run_matrix(task_ids: list[str], interfaces: list[str], k: int, cfg: dict, out_dir: Path,
               workers: int = 1) -> tuple[list[dict], str | None]:
    """Run every (task, interface, run) once. Returns (records, stop_reason or None)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "trajectories").mkdir(exist_ok=True)
    (out_dir / "STOP").unlink(missing_ok=True)
    jobs = [Job(t, i, r) for r in range(k) for i in interfaces for t in task_ids]
    manifest = {
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": {k_: v for k_, v in cfg.items() if k_ != "ledger"},
        "tasks": task_ids, "interfaces": interfaces, "k": k, "workers": workers,
        "max_turns": MAX_TURNS, "git_commit": _git_commit(),
    }
    if cfg["agent"] == "model":
        from .models import PRICES
        manifest["prices_per_mtok"] = {cfg["model"]: PRICES[cfg["model"]]}
    workers = max(1, min(workers, len(jobs)))
    chunks = [(jobs[i::workers], cfg, str(out_dir)) for i in range(workers)]
    if workers == 1:
        results = [_worker(chunks[0])]
    else:
        with mp.get_context("spawn").Pool(workers) as pool:
            results = pool.map(_worker, chunks)
    records = sorted((r for rs in results for r in rs), key=lambda r: (r["task"], r["interface"], r["run"]))
    stop_file = out_dir / "STOP"
    stop_reason = stop_file.read_text() if stop_file.exists() else None
    manifest["ended"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest["runs_recorded"] = len(records)
    manifest["runs_planned"] = len(jobs)
    manifest["stop_reason"] = stop_reason
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    with open(out_dir / "runs.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return records, stop_reason


ALL_TASK_IDS = [t.id for t in TASKS]
