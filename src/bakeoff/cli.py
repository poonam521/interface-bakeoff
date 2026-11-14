"""bakeoff CLI.

  bakeoff run       run tasks x interfaces x k (fake agent by default; --agent model spends money)
  bakeoff report    build report.md / report.json / chart.png for a results directory
  bakeoff silentfail  score the silent-fault detector (no model calls)
  bakeoff budget    show the spend ledger
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .budget import HARD_CAP_USD, BudgetGuard
from .harness import ALL_TASK_IDS, run_matrix
from .interfaces import INTERFACES
from .models import PRICES
from .report import build
from .tasks import PILOT_TASKS, select

RESULTS = Path("results")
LEDGER = RESULTS / "spend_ledger.json"
# Rough planning numbers per run, before any measurement: (model turns, input tokens per turn).
ROUGH = {"screenshot": (12, 3500), "a11y": (10, 3000), "api": (6, 2500)}
ROUGH_OUTPUT_PER_TURN = 400


def rough_estimate(model: str, tasks: int, interfaces: list[str], k: int) -> float:
    p_in, p_out, *_ = PRICES[model]
    total = 0.0
    for i in interfaces:
        turns, tin = ROUGH[i]
        total += tasks * k * turns * (tin * p_in + ROUGH_OUTPUT_PER_TURN * p_out) / 1e6
    return total


def _cfg(a) -> dict:
    if a.agent == "fake":
        return {"agent": "fake", "mode": a.mode, "fail_rate": a.fail_rate, "seed": a.seed}
    return {"agent": "model", "model": a.model, "effort": a.effort, "max_tokens": a.max_tokens,
            "cap": a.cap, "ledger": str(LEDGER)}


def cmd_run(a) -> int:
    tasks = [t.id for t in select(a.tasks.split(",") if a.tasks else None)]
    ifaces = a.interfaces.split(",")
    bad = [i for i in ifaces if i not in INTERFACES]
    if bad:
        print(f"unknown interface(s): {bad}; choose from {INTERFACES}")
        return 2
    if a.pilot:
        tasks, k = list(PILOT_TASKS), 1
    else:
        k = a.k

    if a.agent == "model":
        if a.model not in PRICES:
            print(f"no price on file for {a.model}; known: {', '.join(PRICES)}")
            return 2
        guard = BudgetGuard(LEDGER, a.cap)
        guard.clear_reservations()
        est = rough_estimate(a.model, len(tasks), ifaces, k)
        print(f"Model {a.model}; {len(tasks)} tasks x {len(ifaces)} interfaces x k={k} = "
              f"{len(tasks) * len(ifaces) * k} runs. Rough pre-measurement estimate: ${est:.2f}. "
              f"Spent so far: ${guard.spent():.4f} of ${a.cap:.2f} cap.")
        if a.dry_run:
            return 0
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set in this shell. Nothing was run.")
            return 2
    elif a.dry_run:
        print(f"Fake agent: {len(tasks) * len(ifaces) * k} runs, no cost.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = a.name or f"{stamp}-{'pilot' if a.pilot else a.agent}"
    out = Path(a.out) / name
    records, stop = run_matrix(tasks, ifaces, k, _cfg(a), out, workers=a.workers)
    build(out)
    print(f"\nWrote {len(records)} runs to {out}")
    print((out / "report.md").read_text(encoding="utf-8").split("## Effort")[0])
    if a.agent == "model":
        guard = BudgetGuard(LEDGER, a.cap)
        print(f"Spend ledger: ${guard.spent():.4f} of ${a.cap:.2f}")
        if a.pilot:
            per_run = sum(r["cost_usd"] for r in records) / max(1, len(records))
            full = per_run * len(ALL_TASK_IDS) * len(ifaces) * a.k
            print(f"Pilot cost per run ${per_run:.4f}; projected full matrix (k={a.k}): ${full:.2f}; "
                  f"remaining budget ${guard.remaining():.2f}")
            if full > guard.remaining():
                print("PROJECTION EXCEEDS THE REMAINING BUDGET. Do not start the full run.")
                return 3
    if stop:
        print(f"STOPPED EARLY: {stop}")
        return 3
    return 0


def cmd_report(a) -> int:
    report = build(Path(a.run_dir))
    print(json.dumps({i: {k: v for k, v in s.items() if k in ("pass_hat_1", "pass_hat_k", "pass_at_k")}
                      for i, s in report["summary"].items()}, indent=2))
    print(f"Wrote report.md, report.json and chart.png in {a.run_dir}")
    return 0


def cmd_silentfail(a) -> int:
    from silentfail.score import score, to_markdown
    res = score(seeds=a.seeds, rate=a.rate)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "silentfail.json").write_text(json.dumps(res, indent=2))
    md = to_markdown(res)
    (out / "silentfail.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_budget(_a) -> int:
    g = BudgetGuard(LEDGER)
    print(f"Spent ${g.spent():.4f} of the ${HARD_CAP_USD:.2f} hard cap; ledger {LEDGER}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bakeoff")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the task matrix")
    r.add_argument("--agent", choices=["fake", "model"], default="fake")
    r.add_argument("--mode", choices=["perfect", "liar", "clumsy", "flaky"], default="perfect")
    r.add_argument("--fail-rate", type=float, default=0.3)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--model", default="claude-haiku-5-5")
    r.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    r.add_argument("--max-tokens", type=int, default=4000)
    r.add_argument("--cap", type=float, default=HARD_CAP_USD, help=f"may only lower the ${HARD_CAP_USD:.0f} cap")
    r.add_argument("--tasks", help="comma-separated task ids (default: all)")
    r.add_argument("--interfaces", default=",".join(INTERFACES))
    r.add_argument("-k", type=int, default=5)
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--pilot", action="store_true", help="3 tasks x interfaces x 1 run, then project the full cost")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--out", default=str(RESULTS))
    r.add_argument("--name")
    r.set_defaults(fn=cmd_run)

    rp = sub.add_parser("report", help="build the report for a results directory")
    rp.add_argument("run_dir")
    rp.set_defaults(fn=cmd_report)

    sf = sub.add_parser("silentfail", help="score the silent-fault detector")
    sf.add_argument("--seeds", type=int, default=20)
    sf.add_argument("--rate", type=float, default=0.5)
    sf.add_argument("--out", default=str(RESULTS / "silentfail"))
    sf.set_defaults(fn=cmd_silentfail)

    b = sub.add_parser("budget", help="show spend so far")
    b.set_defaults(fn=cmd_budget)

    a = p.parse_args(argv)
    if getattr(a, "cap", 0) > HARD_CAP_USD:
        p.error(f"--cap cannot exceed ${HARD_CAP_USD:.2f}")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
