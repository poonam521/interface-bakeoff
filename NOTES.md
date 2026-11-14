# Decision notes

Short log of decisions, newest at the bottom.

## 2026-11-14

- **Location.** Project lives in `Downloads\verifieraudit\interface-bakeoff\`, a new subfolder,
  so the unrelated `verifieraudit.zip` in the parent folder stays outside the repo untouched.
- **Research.** All four named papers were found and opened on arXiv. The benchmark is spelled
  "ToolMaze" in the paper. Two extra GUI/CLI papers appeared in search but were not opened, so
  they are named in `docs/research.md` as unread and not relied on.
- **Virtual environment.** `.venv` inside the project; Flask, anthropic and pytest installed
  there only. Nothing system-wide.
- **No API key on this machine.** `ANTHROPIC_API_KEY` is not set at process, user or machine
  level, and there is no `ant` CLI profile. Consequence: the Phase 2 proof of concept was run
  with a scripted stand-in for the model. The real model call in the PoC and the Phase 5 real
  run are both blocked until a key is set.
- **PoC shape.** Flask + SQLite ticket app, typed-tool interface, one task, verdict from reading
  the SQLite file directly, including a check that no other row changed. Kept under `poc/` as a
  record; the real build goes under `src/`.
- **Manual agent loop, not the SDK tool runner.** The harness needs to count steps, meter cost
  before each call, trim old screenshots and stay provider-agnostic, so it owns the loop.
- **Agent's claim is a tool call.** `finish(outcome)` gives a structured claim to compare with
  the database, instead of parsing free text.
- **Own function tools for all three interfaces**, not a vendor computer-use tool, so the
  comparison does not depend on one provider's feature.
- **Model for the real run: undecided, user's call.** Estimates in `docs/architecture.md` say
  only Claude Haiku 5.5 fits k=5 across 225 runs under $10. Recommendation is Haiku 5.5.
- **Open questions for the user** (asked at the Phase 3 stop): approve architecture and task
  list; model; GitHub account to own the repo; commit author identity; whether to omit Claude
  attribution lines; how the API key will be provided.
- No commits yet: waiting for the author identity answer so history does not need rewriting.

## 2026-11-14 (build, after approval)

- **Architecture approved** by the user as proposed.
- **Stateless model turns.** Each request = system + one user message (task, action log, current
  view). Replaces "keep the last two screenshots". Reason: per the Anthropic migration guide,
  Haiku 5.5 / Sonnet 5.5 / Opus 5.5 return a 400 when a replayed thinking block follows edited
  history; a fresh request per turn never replays one. Same shape for every provider.
- **No `temperature`.** Current Claude models reject sampling parameters; runs use defaults.
- **No server-side model fallback.** The SDK guidance enables fallbacks by default for some
  models; here it would silently swap the model mid-benchmark, so refusals are recorded as
  `model_error` instead. Haiku 5.5 has no server-side fallback anyway.
- **Effort `medium`** by default (Haiku 5.5's own default), set explicitly; `--effort` overrides.
- **Prices** live in `bakeoff/models.py` (Haiku 5.5: $0.10/$0.50 per MTok, cache read 0.1x,
  write 1.25x). The budget's worst case prices every input token at the cache-write rate and
  assumes the full `max_tokens` of output, so it over-reserves on purpose.
- **Budget ledger** is `results/spend_ledger.json`, shared by worker processes through a lock
  file. The cap constant is $10.00; `--cap` can only lower it.
- **Fake agent for browser interfaces** uses CSS selectors from the task file and asks the
  interface to translate them (refs for a11y, scroll + pixel coordinates for screenshot).
- **Task detail changed from the proposal:** in `search_close_matching` the distractor is a
  ticket that mentions VPN only in its *description* (ticket 10), not in a comment, because the
  app's search matches title and description.
- **silentfail scoring rule:** a flag on a clean call right after an undetected fault counts as a
  delayed detection of that fault, not a false positive. The detector only remembers timestamps
  from results that passed its checks; before that fix, one caught phantom write caused a
  knock-on false flag on the next honest read (60 false positives, now 0).
- **SDK detail:** anthropic 2.8 is built on `httpx2`, not `httpx`; the model tests build error
  objects with it.
- Bugs found while building, both fixed: a Flask helper argument named `status` collided with the
  page's `status` filter variable (HTTP 500 on the home page); Playwright treated JS snippets with
  a leading newline as expressions, not functions.
- **User decisions:** repo under gh account `poonam521`, private; commits authored as
  Poonam Singh S (noreply address), set for this repo only; no Claude attribution lines in commit
  messages; real run on **Claude Sonnet 5.5**. My rough pre-pilot estimate for Sonnet at k=5 is
  above the $10 cap, so the real run starts with the 9-run pilot and stops if the measured
  projection does not fit; reducing k or the task count would then be the user's call.
- **Still blocked:** the real run. `ANTHROPIC_API_KEY` is not set at process, user or machine
  level, and there is no `ant` CLI profile.
