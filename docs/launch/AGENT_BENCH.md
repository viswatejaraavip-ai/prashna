# Agent benchmark — latency and cost of one consultation

Owner: AI pipeline workstream. The tool is `backend/scripts/agent_bench.py`;
this file records what it measured and what was changed because of it.

## Running it

```bash
cd backend

# free: fakes with injected latency, no API calls, no money
../.venv/bin/python scripts/agent_bench.py --dry-run

# the real thing (see "What a run costs" below)
ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
  ../.venv/bin/python scripts/agent_bench.py --runs 3 --json after.json

# A/B against a stored run
../.venv/bin/python scripts/agent_bench.py --runs 3 --compare before.json

# prove the SSE route streams end to end (this one charges a real wallet)
../.venv/bin/python scripts/agent_bench.py --cases lookup \
  --http https://<cloud-run-url> --token <app JWT> --profile <profile id>

# reasoning-model A/B
../.venv/bin/python scripts/agent_bench.py --runs 3 --label opus45 --json opus45.json
../.venv/bin/python scripts/agent_bench.py --runs 3 --model claude-opus-5 \
  --effort low --label opus5-low --json opus5-low.json --compare opus45.json
```

The suite is seven turns: `career/te`, a real follow-up to it (`career+followup/te`,
which only makes sense from the session summary the first turn wrote),
`marriage/hi`, `health/ta`, `money/kn`, `general/ml`, and `lookup/en` (a narrow
factual question that takes the no-brief path). Every number comes out of the
pipeline's own trace, so it is exactly what the operator dashboard will show.

**What a run costs.** Real mode spends provider money: about **₹3 per turn**, so
roughly **₹22 for one pass** of the seven cases and **₹66 for `--runs 3`**. The
script prints the exact total it spent at the end of every run. `--dry-run`
spends nothing.

### The four latency numbers, and which one is "the answer took N seconds"

| Number | What it is |
|---|---|
| **first token** | The first streamed delta. What the user sees the app come alive. |
| **answer complete** | The SSE `done` event: the whole answer is on screen. |
| **POST /ask returns** | The non-streaming route's response. |
| incl. background | Bench-only: also joins the post-answer bookkeeping thread. No user ever waits for this. |

## Baseline (before this work)

Measured by the owner on a real query, 2026-09-19:

| | |
|---|---|
| End to end | **26.7 s** |
| Cost | **₹3.24** (plan 0.08 + brief 0.69 + reason 2.41 + memory 0.06) |

Stage-by-stage baselines from the structural measurements below:

| Stage | Model | Cost | What dominates it |
|---|---|---|---|
| plan | Flash-Lite | ₹0.08 | ~1.6k in / 140 out — small |
| tools | engine (local) | ₹0 | **7 ms** — measured, not a latency factor at all |
| brief | Flash-Lite | ₹0.69 | ~12k input tokens, ~1.2–1.5k output tokens |
| reason | Opus 4.5 | ₹2.41 | **decoding ~800 output tokens** — the bulk of the 26.7 s |
| memory | Flash-Lite | ₹0.06 | ~1k in / 260 out, and it was **blocking the response** |

## Measurements that decided the work

These were run locally and are reproducible; they are real numbers, not estimates.

**1. Engine tools are not the problem.** The "run tools concurrently with the
plan" idea was killed by measurement:

| Tools | Latency | Raw JSON |
|---|---|---|
| `full_analysis` | **7 ms** | 35,468 chars |
| `full_analysis` + `varga_chart(D10)` | **7 ms** | 36,470 chars |
| `current_dasha` | 2 ms | 409 chars |
| `dosha_analysis` | 323 ms | 5,606 chars |

Overlapping a 7 ms computation with a ~1 s Flash call buys 7 ms. Not done.

**2. Deterministic pruning of engine JSON** (`executor.prune`) — ISO timestamps
to dates, degrees to 2 dp, dasha period lists windowed around today:

| Tool output | Before | After | Saved |
|---|---|---|---|
| `full_analysis` | 35,468 ch (~11.8k tok) | 22,777 ch (~7.6k tok) | **−36 %** |
| `full_analysis` + D10 | 36,470 ch | 23,663 ch | −35 % |
| `dosha_analysis` | 5,606 ch | 1,746 ch | −69 % |
| `current_dasha` | 409 ch | 233 ch | −43 % |

Inside `full_analysis` the `dashas` block goes 10,990 → 3,749 chars and `nadi`
8,089 → 5,935. That is ~4,200 fewer Flash input tokens per query.

**3. Prompt caching does not apply.** Opus 4.5's minimum cacheable prefix is
**4,096 tokens**. The reasoner system prompt is 3,673 chars ≈ **1,268 tokens**
(pessimistic estimate; real count lower). It would silently never cache —
`cache_creation_input_tokens: 0`, no error. **Not implemented.** It becomes
viable only if the system prompt grows past 4k tokens (bad: that costs more
than caching saves) or the model moves to Opus 5, whose minimum is 512 tokens
— at which point caching the system prompt saves ~0.1 × 1,268 × 0.045 ≈ **₹0.51
per query** on cache hits. Revisit with the Opus 5 decision below.

**4. SSE is not gzipped.** `main.py` wraps the app in `GZipMiddleware`, which
would buffer the whole answer and destroy TTFT. Starlette 0.49.3 excludes
`text/event-stream` (`DEFAULT_EXCLUDED_CONTENT_TYPES`), so the stream is safe
today. Pinned by `test_sse_is_not_gzipped_by_the_app_middleware` so a Starlette
downgrade cannot silently reintroduce it.

## What changed

| # | Change | Effect | Risk |
|---|---|---|---|
| 1 | **Post-answer work moved off the request thread** (`pipeline.ASYNC_TAIL`) — memory update, message/session writes, trace and rollups | `POST /ask` returns ~1.5 s (a Flash call) + ~5 Firestore writes sooner | Status can no longer flip to `over_ceiling` because of the memory call after `done` was sent; the memory reserve makes that essentially impossible |
| 2 | **Brief skipped when engine output is small** (`AI_BRIEF_SKIP_MAX_CHARS=4500`) — the pruned JSON goes straight to Opus | One fewer serial model round trip on narrow questions | Opus reads JSON instead of prose; budgeted on the real token count |
| 3 | **Deterministic pruning** (measurement 2) | −36 % Flash input tokens, ~₹0.11/query | Windowing drops very old dasha periods; 2 most recent past periods kept |
| 4 | **Exact token count only when it can change the answer** | One round trip (~0.2–0.5 s) saved whenever the pessimistic estimate already affords the full output cap | None: the estimate is a proven upper bound (`test_the_estimate_is_an_upper_bound_...`) |
| 5 | **Lower effort for lookup intents** (`panchanga, festival, muhurta, greeting` → `low`) | Faster, cheaper on factual turns | Readings (career/marriage/health/money) keep the default |
| 6 | **Client warm-up at startup** (`llm.warm_clients_async`) | Moves SDK import + TLS handshake off the first query of a cold Cloud Run instance | None; daemon thread, never fails startup |
| 7 | **Context reads in parallel** (profile + memory + other profiles) | 3 serial Firestore round trips → 1 | None |
| 8 | **The agent is told what day it is** (`ai/clock.py`) | Correctness fix, see below | Slightly longer system prompt (kept tight) |

### Measured A/B of the orchestration changes

Both runs use `--dry-run` (identical injected model latencies), so this isolates
what the *orchestration* changed and excludes model-side wins:

```
                                    before     after   change
    first token p50                  7.26s     7.25s    -0.2%
    first token p95                  7.28s     7.26s    -0.2%
    answer complete p50 (SSE)       19.15s    19.15s    +0.0%
  ✓ POST /ask returns p50           20.66s    19.16s    -7.3%
  ✓ POST /ask returns p95           20.67s    19.17s    -7.3%
  ✓ cost per query (mean)            3.51₹     3.37₹    -4.0%
```

Per case, the narrow question shows what dropping a serial model call does:

| case | first token | answer complete | cost |
|---|---|---|---|
| `career/te` (wide reading) | 7.25 s | 19.2 s | ₹3.50 |
| `lookup/en` (**no-brief path**) | **3.03 s** | 15.4 s | **₹2.64** |

`--dry-run` cannot model input-size-dependent Flash latency, so the pruning win
(measurement 2) shows up as cost here and as prefill time in a real run.

### Where the 26.7 s actually goes

`tools` is 7 ms, so essentially all of it is model time, and **Opus decoding
~800 Indic output tokens is the majority**. That cannot be removed without
shortening the answer, which is the product. So the target that matters is
**time to first token**, and the levers are everything that happens *before*
Opus starts: plan → tools → brief → count-tokens → Opus TTFT. Changes 2, 3, 4
and 6 all attack exactly that window; change 1 attacks the tail after it.

## Still open — needs an API key to finish

`ANTHROPIC_API_KEY` / `GEMINI_API_KEY` were not available in this environment,
so **no real-model numbers were produced**. Everything above is either a local
measurement (engine, pruning, token counts, middleware) or a fake-latency A/B
of the orchestration. To close it out:

```bash
cd backend
export ANTHROPIC_API_KEY=... GEMINI_API_KEY=...
../.venv/bin/python scripts/agent_bench.py --runs 3 --label after --json after.json --replies 400
```

`--replies 400` prints the start of every answer, which is the Telugu/Hindi
quality spot-check.

### Opus 4.5 vs Opus 5

Opus 5 lists at the **same** per-token price as Opus 4.5 ($5 in / $25 out per
MTok; both rows are in `costs.py`). It is still not automatically the same cost
per query, for one reason:

> On Opus 5 **adaptive thinking is on by default**, thinking tokens are billed
> as **output** ($25/MTok), and they are spent **inside `max_tokens`**.

Two consequences, both handled in code:

* **Cost.** The same answer can carry hundreds of extra output tokens. At
  ₹0.225/output token, 400 thinking tokens is **₹0.90** — a third of today's
  whole query cost. This is the thing to measure.
* **Truncation.** With today's `max_tokens` (1,400 for text) reasoning could eat
  the budget and cut the answer short. `budget.THINKING_HEADROOM` (1.8×) widens
  both the cap and the minimum we insist on for a thinking model, while
  `budget.answer_tokens()` keeps the *length target* we ask for unchanged —
  so the reply stays the same length and the cap just leaves room to think.
  The ₹5 ceiling is enforced identically either way (`max_tokens` caps total
  output, thinking included) and is covered by
  `test_thinking_model_still_cannot_exceed_the_ceiling`.

Other API differences, from the `claude-api` skill, already accounted for:
`budget_tokens` is rejected on Opus 5 (we never send it — depth is set with
`output_config.effort`); `thinking: {type: "disabled"}` is accepted only at
effort `high` or below, and the skill warns it can make Opus 5 emit tool calls
or `<thinking>` tags as visible text, so **lowering effort is preferred over
disabling thinking**. `llm.opus()` drops `thinking` and then `output_config`
one at a time on a 400 rather than failing the query.

**Decision: stay on `claude-opus-4-5` until measured.** The switch is a
one-flag change (`CLAUDE_MODEL`), the price table and budget rules are ready,
and the bench takes the comparison directly:

```bash
../.venv/bin/python scripts/agent_bench.py --runs 3 --label opus45  --json opus45.json --replies 400
../.venv/bin/python scripts/agent_bench.py --runs 3 --label o5-low  --model claude-opus-5 --effort low    --json o5-low.json  --compare opus45.json --replies 400
../.venv/bin/python scripts/agent_bench.py --runs 3 --label o5-med  --model claude-opus-5 --effort medium --json o5-med.json  --compare opus45.json --replies 400
```

Switch only if `cost per query (mean)` is **not higher** and first-token /
answer-complete and the Telugu + Hindi spot-checks hold.

## Configuration added

All default to the behaviour described above; each can be turned off.

| Env | Default | Effect |
|---|---|---|
| `AI_ASYNC_TAIL` | `1` | `0` = memory/trace/rollups inline again |
| `AI_TAIL_TIMEOUT_S` | `60` | Join timeout for `Result.wait()` |
| `AI_BRIEF_SKIP_MAX_CHARS` | `4500` | `0` = always call Flash for the brief |
| `AI_PRUNE_ENGINE_JSON` | `1` | `0` = feed raw engine JSON |
| `AI_PRUNE_PAST_PERIODS` / `AI_PRUNE_FUTURE_PERIODS` | `2` / `4` | Dasha window |
| `AI_PRUNE_PAST_YEARS` / `AI_PRUNE_FUTURE_YEARS` | `2` / `5` | Year-timeline window |
| `AI_WARM_CLIENTS` | `1` | Build SDK clients at startup |
| `CLAUDE_COUNT_TOKENS_ALWAYS` | `0` | `1` = always pay for the exact count |
| `CLAUDE_LOW_EFFORT_INTENTS` | `panchanga,festival,muhurta,greeting` | Intents that get `CLAUDE_EFFORT_SIMPLE` |
| `CLAUDE_EFFORT_SIMPLE` | `low` | `""` disables the step-down |
| `CLAUDE_THINKING` | `""` (model default) | `adaptive` \| `disabled` |
| `CLAUDE_THINKING_HEADROOM` | `1.8` | Output-cap multiplier for a thinking model |
| `AI_CLOCK_FROZEN` | — | ISO instant; pins "now" (tests) |

## The agent's sense of "now"

`backend/app/ai/clock.py` is the single source of the current moment, in **IST**
(fixed +05:30, no tzdata needed), and every stage gets the same string:

```
Now: Sunday, 20 September 2026, 14:35 IST (2026-09-20).
```

* **reasoner** — `Now:` is the first line of the request, and the system prompt
  tells Opus its own sense of the date is training data and must never be used;
  every date in the brief is compared against `Now:` to decide past vs future.
* **executor / brief** — the same stamp, plus an instruction to label every
  period `(past)`, `(RUNNING NOW)` or `(upcoming)` against it. The no-brief path
  carries the stamp in its preamble so Opus dates raw JSON the same way.
* **planner** — `now` alongside `today`, so "next year" in the question resolves
  to the same year everywhere.
* **memory** — told to record times absolutely ("asked in September 2026"),
  never relatively ("last month"), because the summary is read back weeks later.
* **engine windows** — `executor.prune` windows dasha periods and
  `run_tools` defaults `year` / `year_of_varsha` from the same clock, so "running
  now" in the data always agrees with the `Now:` the model was given.

Covered by `test_reasoner_request_carries_the_current_date` (frozen clock),
`test_every_model_stage_gets_the_same_now` and `test_clock_is_ist_not_utc`
(22:30 UTC must read as the 21st in India).
