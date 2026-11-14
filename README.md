# interface-bakeoff

**Does an AI agent finish the same web task more reliably when it sees screenshots, the
accessibility tree, or a small typed API?** And when a tool quietly returns wrong data, can we
tell?

This repo gives one LLM agent the same 15 tasks on the same small web app through three
interfaces. Each task runs several times, and the app's database decides pass or fail. The
headline number is **Pass^k: the share of tasks the agent passes in *every one* of k runs**, not
the share of runs that pass. A second module, `silentfail`, injects plausible-but-wrong tool
results and measures how well cheap checks catch them.

## Why it matters

An agent that succeeds 80% of the time per run might complete only half your tasks reliably,
because the failures land on different tasks each time. Recent work measured this gap for
desktop agents ([Gonzalez-Pumariega et al., 2026](https://arxiv.org/abs/2604.17849): about 78%
of tasks solved at least once in 10 tries, about 36% solved in all 10). Interface choice is
usually compared on single-run success. For anyone automating web work (test engineers included),
the useful question is which interface gives results you can **repeat**, and whether you can
notice when the agent or its tools are wrong. Sources are summarised in
[docs/research.md](docs/research.md).

## How it works

- **App**: "Deskline", a small ticket tracker written for this project (Flask + SQLite, 30 seeded
  tickets, forms with validation, search, comments, delete with confirmation). Reset to an
  identical seed before every run.
- **Three interfaces, same model, same tools format**:
  - `screenshot`: the agent sees only a 1024Ã—768 PNG and clicks pixels, types, scrolls.
  - `a11y`: the agent sees a text snapshot of the page with element refs (`[e7]`) and acts by ref.
  - `api`: the agent calls typed tools (`search_tickets`, `update_ticket`, ...) and never sees the page.
- **15 tasks**: forms, edits, multi-step flows, search, deletes and one impossible task. The list
  is in [docs/architecture.md](docs/architecture.md).
- **Verification by state, never by the agent's word.** After each run the verifier reads the
  SQLite file directly: the expected changes must be there, and *nothing else* may have changed.
  Every single action is also checked (did it touch anything outside the task's scope?). The
  agent's own "done" is recorded only to count **false success claims**.
- **Cost controls**: a hard $10 cap in code across all real runs, a persistent spend ledger, a
  worst-case check before every model call, a pilot run that projects the full cost first.
- **Fake agent**: a scripted agent replays reference solutions through each interface (or lies,
  breaks things, or fails at a seeded rate), so the whole harness is tested with no key and no cost.

## Results

### Harness check with the fake agent (not model results)

`results/fake-flaky-k5/` is the scripted fake agent in `flaky` mode: it skips a task in a seeded
15% of runs and claims "done" anyway. It shows the measurement doing its job: the per-run pass
rate stays high, but the all-runs rate drops sharply, and every skipped run is caught as a false
success claim.

| Interface | Pass^5 | Pass^1 | Pass@5 | False success claims |
|---|---|---|---|---|
| screenshot | 67% | 91% | 100% | 7 of 75 runs |
| a11y | 47% | 83% | 100% | 13 of 75 runs |
| api | 33% | 83% | 100% | 13 of 75 runs |

The differences between interfaces here are pure chance from the seed; they say nothing about
real agents. With `--mode perfect` every task passes on every interface (checked in the test suite).

### silentfail (no model calls)

`results/silentfail/` scores the detector on scripted API traces for all 15 tasks, 20 seeds,
with a fault injected into half of the eligible tool calls (407 faults, 593 clean calls).

| Detector | Precision | Recall | False positives |
|---|---|---|---|
| Tier 1: invariants only (no extra calls) | 99.6% | 58.5% | 1 of 593 clean calls |
| Tier 1 + 2: invariants plus cross-checks | 100.0% | 100.0% | 0 of 593 clean calls |

Invariants alone miss most phantom writes (34.7% caught), truncated lists (33.3%) and corrupted
fields (47.1%). Cross-checks cost 0.86 extra API calls per agent call. The perfect tier 1 + 2 score
holds only because these injected faults are transient: asking again by another route returns
the truth. A fault that persists across every route would beat these cross-checks; see
Limitations.

## Run it

Python 3.11+.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

```bash
.venv/Scripts/python -m playwright install chromium
```

(On macOS or Linux use `.venv/bin/` instead of `.venv/Scripts/`.)

Tests and fake-agent runs, no key, no cost:

```bash
.venv/Scripts/python -m pytest
```

```bash
.venv/Scripts/bakeoff run --agent fake --mode flaky -k 5 --workers 3
```

```bash
.venv/Scripts/bakeoff silentfail
```

A real run. It needs `ANTHROPIC_API_KEY` in the environment and stops itself at the cap.

```bash
.venv/Scripts/bakeoff run --agent model --model claude-sonnet-5-5 --dry-run
```

```bash
.venv/Scripts/bakeoff run --agent model --model claude-sonnet-5-5 --pilot
```

```bash
.venv/Scripts/bakeoff run --agent model --model claude-sonnet-5-5 -k 5 --workers 3
```

```bash
.venv/Scripts/bakeoff report results/<run-name>
```

```bash
.venv/Scripts/bakeoff budget
```

Each run writes `results/<run-name>/`: `manifest.json`, `runs.jsonl` (one line per run), one
trajectory per run with every action and its per-step database diff, plus `report.md`,
`report.json` and `chart.png`.

## Limitations

- One small app written for this project, 15 tasks, one model. Results will describe this setup,
  not interfaces in general. With 15 tasks the confidence intervals are wide; the report prints them.
- Current Claude models do not accept a temperature setting, so run-to-run variation is whatever
  the model does by default.
- The agent gets a fresh request each turn (task, log of past actions, current view) rather than
  a growing chat. It is the same for all three interfaces, but an agent with full conversation
  memory could behave differently.
- The fake agent's browser solutions use CSS selectors; it proves the harness, not that the tasks
  are easy or hard for a model.
- silentfail faults are transient and scored on scripted traces, not on model runs. Its cross-checks
  go through the same API, so a fault that persists across every route would not be caught.
- Model refusals are recorded as `model_error`. Server-side fallback to another model is
  deliberately off, so every run is scored on the model that was asked.

## Layout

```
src/bakeoff/     app/ (Flask + SQLite), tasks.py, interfaces/, agents.py, models.py, budget.py,
                 harness.py, verify.py, metrics.py, report.py, cli.py
src/silentfail/  injector.py, detector.py, score.py
tests/           unit tests per module, end-to-end tests with the fake agent
docs/            research.md, architecture.md
poc/             the Phase 2 proof of concept, kept as a record
results/         raw results of every run, and the spend ledger
```
