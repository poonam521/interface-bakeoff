# Research notes

Read on 2026-11-14. Each paper below was opened on arXiv (HTML version). Numbers are quoted
from the part of each page that was read verbatim; anything that came only from a search
snippet or a machine summary is marked *(unverified)*. Nothing here is from memory.

## 1. Repeated-run reliability of computer-use agents

**On the Reliability of Computer Use Agents** — Gonzalez-Pumariega, Agashe, Yang, Li, Wang,
20 Apr 2026. <https://arxiv.org/abs/2604.17849>

- Measured: the same OSWorld tasks run repeatedly, across GPT-5, Claude Sonnet 4.6, Kimi 2.5,
  Qwen-3VL-8B, OpenCUA and UI-TARS-1.5-7B.
- Metric: `Pass^k = E_x[ C(c_x, k) / C(n, k) ]`, where `c_x` is the number of successes in `n`
  runs of task `x`. `Pass^1` is the ordinary success rate; `Pass^n` is the share of tasks that
  pass on **all** `n` runs. Reliability is defined as "the probability that all executions of
  the same task succeed."
- Result: with Agent S3 + GPT-5, Pass@10 (any of 10 runs) is about 78% but Pass^10 (all 10) is
  about 36%. With n=3: GPT-5 0.576 → 0.454, Claude 0.702 → 0.612, Kimi 0.508 → 0.357
  (Pass^1 → Pass^3).
- Also: clearer instructions raised GPT-5 Pass^3 from 0.454 to 0.576; a cosmetic change to the
  environment lowered Claude Pass^3 from 0.612 to 0.557.
- Scope: one interface only (screenshots, desktop). Total task count *(unverified)*.

## 2. GUI versus CLI agents

**GUI vs. CLI: Execution Bottlenecks in Screen-Only and Skill-Mediated Computer-Use Agents** —
Zhou, Zhang, Zhao, Wei, Song, Cohan, Zhao, 22 Jun 2026. <https://arxiv.org/abs/2606.24551>

- Measured: 440 desktop tasks, 18 applications, 12 workflow categories, the same task and the
  same verifier for a screenshot-only agent and a CLI agent using a skill layer.
- Metric: full pass rate (every verifier check must pass) and average task time.
- Result: best GUI agent (GPT-5.4) 59.1%; best CLI agent with the original skills (Codex
  GPT-5.5) 48.2%; with verifier-guided skill repair 69.3%, which the authors call a diagnostic
  upper bound, not a deployable baseline. The original skills covered 37.6% of verifier
  checkpoints.
- Scope: I found no statement of repeated runs, seeds or confidence intervals on the page, so
  this is single-run success as far as I can tell. No accessibility-tree condition.

Two related papers turned up in search but were **not opened**, so they are not relied on:
OpenComputer (arXiv 2605.19769) and CUAWright (arXiv 2610.04116).

## 3. ToolMaze — implicit tool failures

**When Tools Fail: Benchmarking Dynamic Replanning and Anomaly Recovery in LLM Agents** — Zhu
et al., 4 Jun 2026. <https://arxiv.org/abs/2606.05806> (the paper spells it "ToolMaze")

- Measured: 400 base tasks over 270 tools, expanded to 2,000 instances by a 2×2 fault taxonomy:
  explicit/implicit × transient/permanent. Explicit faults are machine-readable errors such as
  HTTP 404; "implicit failures generate structurally compliant but semantically flawed outputs."
- Metrics: task success rate, Perturbation Recovery Rate (PRR), and a recovery-cost score.
- Result: recovery collapses on implicit faults. Claude Sonnet 4.6 without a hint: PRR 59.68
  (explicit-transient) and 27.68 (explicit-permanent) versus 5.08 and 7.08 for the two implicit
  types. GPT-5.5: 86.09 / 29.49 versus 18.89 / 14.75. The abstract attributes a roughly 37%
  PRR drop to "systemic over-trust in corrupted outputs."
- Scope: measures whether the *agent* recovers. Procedurally generated tool graphs, not a web
  app *(limitations section read only as a summary)*.

## 4. ToolFailBench — tool-skip, result-ignore, output-fabrication

**ToolFailBench: Diagnosing Tool-Use Failures in LLM Agents** — Harsh Soni, 6 Jul 2026.
<https://arxiv.org/abs/2607.04686>

- Measured: 1,000 single-turn tasks in five domains; 750 where the mock tool's answer
  contradicts what the model probably memorised, 250 controls needing no tool.
- Labels: Tool-Skip ("does not produce a valid executed tool call"), Result-Ignore ("calls the
  tool but does not use the returned data"), Output-Fabrication ("adds invented structured
  information not present in the return"), plus Unnecessary-Tool-Use on controls. Labelled by a
  rule classifier and two LLM judges, majority vote.
- Result: best Clean Tool-Use Rate is 86.33% (Grok-4.3) across 19 headline models.
- Scope, in the author's words: the single-turn format "does not capture multi-turn failures
  such as tool chaining, recovery from earlier mistakes, or state updates across interactions."

## What this project adds

It is small, and it does not compete with any of these on scale. What it does is put four
ideas that are studied separately into one harness a tester can run on a laptop:

1. **Interface is the variable, reliability is the metric.** Paper 1 measures all-k-runs
   reliability on one interface; paper 2 compares interfaces on single-run success. Here the
   same tasks, same app, same model and same verifier run through three interfaces
   (screenshots, accessibility tree, typed API tools) and are scored by Pass^k.
2. **The accessibility tree is a condition of its own**, which is the interface most
   Playwright-based automation actually uses and which paper 2 does not include.
3. **Verification by database state**, with step-level postconditions, never by the agent's
   final message. That also lets the harness count *false success claims*: the agent says done,
   the database disagrees.
4. **Detection, not only recovery, of silent faults.** ToolMaze shows agents over-trust
   well-formed wrong data; ToolFailBench labels failures after the fact with LLM judges. The
   `silentfail` module injects ToolMaze-style implicit faults into a real stateful app and
   scores a cheap, deterministic detector (invariants and cross-checks against app state) by
   precision and recall, in a multi-step setting that ToolFailBench names as out of its scope.

Limits to keep in mind: one small self-written app, 12–15 tasks, one model, k=5. The results
will describe this app and this model, and should not be read as a general ranking of interfaces.
