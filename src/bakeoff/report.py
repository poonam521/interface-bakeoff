"""Turn a results directory into report.md, report.json and chart.png."""
from __future__ import annotations

import json
from pathlib import Path

from .metrics import summarise
from .tasks import BY_ID

ORDER = ("screenshot", "a11y", "api")
# Categorical slots 1-3 of the dataviz skill's validated default palette, in fixed order.
SERIES = {"Pass@k": "#2a78d6", "Pass^1": "#eb6834", "Pass^k": "#1baf7a"}
INK, INK_2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"


def load(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    with open(run_dir / "runs.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return manifest, records


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


def _ci(ci) -> str:
    return "" if not ci else f" ({100 * ci[0]:.0f}-{100 * ci[1]:.0f})"


def _num(x, fmt="{:.1f}") -> str:
    return "n/a" if x is None else fmt.format(x)


def chart(summary: dict, k: int, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ifaces = [i for i in ORDER if i in summary]
    metrics = {"Pass@k": "pass_at_k", "Pass^1": "pass_hat_1", "Pass^k": "pass_hat_k"}
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    width, gap = 0.26, 0.02
    for j, (label, key) in enumerate(metrics.items()):
        xs = [i + (j - 1) * (width + gap) for i in range(len(ifaces))]
        vals = [100 * (summary[f][key] or 0) for f in ifaces]
        bars = ax.bar(xs, vals, width, color=SERIES[label], label=label.replace("k", str(k)), zorder=3)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}", ha="center", va="bottom",
                    fontsize=8, color=INK_2)
    ax.set_xticks(range(len(ifaces)), ifaces, color=INK)
    ax.set_ylim(0, 108)
    ax.set_ylabel("% of tasks", color=INK_2)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(INK_2)
    ax.tick_params(colors=INK_2, length=0)
    ax.set_title(f"Same tasks, three interfaces: any run, per run, all {k} runs", color=INK, fontsize=11,
                 loc="left")
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.09), fontsize=8, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def build(run_dir: Path) -> dict:
    manifest, records = load(run_dir)
    k = manifest["k"]
    summary = summarise(records, k)
    ifaces = [i for i in ORDER if i in summary]
    total = sum(s["total_cost_usd"] for s in summary.values())
    agent = manifest["agent"]
    who = agent.get("model") or f"fake agent ({agent.get('mode')})"

    lines = [
        f"# Results: {run_dir.name}",
        "",
        f"- Agent: **{who}**" + (f", effort {agent['effort']}" if agent.get("effort") else ""),
        f"- Tasks: {len(manifest['tasks'])}; interfaces: {', '.join(manifest['interfaces'])}; k = {k}",
        f"- Runs recorded: {manifest.get('runs_recorded')} of {manifest.get('runs_planned')} planned"
        + (f"; stopped early: {manifest['stop_reason']}" if manifest.get("stop_reason") else ""),
        f"- Started {manifest['started']}, ended {manifest.get('ended')}; git commit {manifest.get('git_commit')}",
        f"- Total model cost of this run: **${total:.4f}**",
        "",
        "## Reliability",
        "",
        f"Pass^{k} is the share of tasks passed in **all** {k} runs. Pass^1 is the per-run pass rate. "
        f"Pass@{k} is the share passed at least once. Brackets: 95% bootstrap interval over tasks.",
        "",
        f"| Interface | Pass^{k} | Pass^1 | Pass@{k} | Tasks with all {k} runs | False success claims |",
        "|---|---|---|---|---|---|",
    ]
    for i in ifaces:
        s = summary[i]
        lines.append(f"| {i} | **{_pct(s['pass_hat_k'])}**{_ci(s['pass_hat_k_ci'])} | "
                     f"{_pct(s['pass_hat_1'])}{_ci(s['pass_hat_1_ci'])} | {_pct(s['pass_at_k'])} | "
                     f"{s['tasks_with_all_k']} of {s['tasks']} | {s['false_success_claims']} of {s['valid_runs']} runs |")
    lines += ["", "![Reliability by interface](chart.png)", "", "## Effort and cost per run (means)", "",
              "| Interface | Actions | Model turns | Tool errors | Input tokens | Output tokens | Cost | Seconds | Total cost |",
              "|---|---|---|---|---|---|---|---|---|"]
    for i in ifaces:
        s = summary[i]
        lines.append(f"| {i} | {_num(s['mean_actions'])} | {_num(s['mean_turns'])} | {_num(s['mean_tool_errors'])} | "
                     f"{_num(s['mean_input_tokens'], '{:,.0f}')} | {_num(s['mean_output_tokens'], '{:,.0f}')} | "
                     f"${_num(s['mean_cost_usd'], '{:.4f}')} | {_num(s['mean_wall_seconds'])} | "
                     f"${s['total_cost_usd']:.4f} |")
    cats = sorted({c for s in summary.values() for c in s["failure_categories"]})
    lines += ["", "## Failed runs by category", ""]
    if cats:
        lines += ["| Category | " + " | ".join(ifaces) + " |", "|---|" + "---|" * len(ifaces)]
        for c in cats:
            lines.append(f"| {c} | " + " | ".join(str(summary[i]["failure_categories"].get(c, 0)) for i in ifaces) + " |")
    else:
        lines.append("No failed runs.")
    lines += ["", f"## Per task: runs passed out of {k}", "",
              "| Task | Category | " + " | ".join(ifaces) + " |", "|---|---|" + "---|" * len(ifaces)]
    for t in manifest["tasks"]:
        cells = []
        for i in ifaces:
            c, n = summary[i]["per_task"].get(t, (0, 0))
            cells.append(f"{c}/{n}" + ("" if n == k else " (incomplete)"))
        lines.append(f"| `{t}` | {BY_ID[t].category} | " + " | ".join(cells) + " |")
    excluded = sum(s["excluded_runs"] for s in summary.values())
    if excluded:
        lines += ["", f"{excluded} run(s) were excluded as harness errors or budget stops; see runs.jsonl."]

    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"manifest": manifest, "summary": summary, "total_cost_usd": round(total, 6)}
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    chart(summary, k, run_dir / "chart.png")
    return report
