# `backend/evals` — accuracy evaluation of the Prashna consultation agent

This is not a unit test. It asks the **deployed product** real questions about
charts whose real life events are already known, then scores how close the
agent's dated windows came. It spends real provider money every time it runs.

```bash
cd backend/evals
python run_eval.py --dry-run      # free. no network. exercises every code path
python run_eval.py                # the real run (~Rs 140 at today's prices)
python run_eval.py --phase report # rebuild RESULTS.md and the PDF, free
python run_eval.py --phase rescore # re-run the FREE scorers over saved answers
```

`--phase rescore` is the one to use after changing a scorer: it recomputes every
deterministic score and the hit/miss verdicts from `out/answers.jsonl` and the
judge output already on disk, then rewrites the report. It costs nothing.

or, from the repo root, `make eval` / `make eval-dry`.

Outputs:

| file | what |
|---|---|
| `out-dry/` | everything a `--dry-run` produces; it never touches `out/` |
| `out/charts.json` | the created profiles and the engine's own rasi + dasha charts (ground truth for the grounding checks) |
| `out/answers.jsonl` | every question, the verbatim reply, the API status and the Firestore trace (cost, latency, tools, intent) |
| `out/scores.jsonl` | deterministic scores + the judge's JSON, one row per answer |
| `out/summary.json` | everything the report prints |
| `RESULTS.md` | the numbers in text form |
| `~/Desktop/Prashna-PlayStore/prashna-agent-evaluation.pdf` | the report |

## Layout

```
golden_set.json   the charts and their KNOWN outcomes, with source + birth-time confidence
questions.json    the questions, per language. None of them contains the answer
manual_review.json  human verdicts on what the automatic checkers flagged
defects.json      the reproducible product bugs this run found, for the owning workstream
client.py         live HTTP API + read-only Firestore (traces) + secret loading
lexicon.py        Jyotish vocabulary in six scripts, for the deterministic scorers
scorers.py        free scorers: script purity, window hit, date anchoring, age floor,
                  dasha/placement grounding, safety, cost
judge.py          the Claude judge: rubric + window extraction (blind to the truth)
summarise.py      aggregation + RESULTS.md
report_pdf.py     the PDF, on the repo's own fpdf2 + Noto Indic stack
run_eval.py       the CLI: setup -> ask -> judge -> report
```

## Design decisions that matter when reading the numbers

- **The judge never sees the true date.** It only extracts the window the answer
  committed to. `scorers.window_hit()` decides hit or miss in Python. The judge
  therefore cannot be nudged into flattering the product.
- **Profile names are anonymous.** The reasoning model is shown the profile name
  (`reasoner._user_block`), so a famous name would hand it the answer from
  training data.
- **A wide window is not a hit.** `exact` needs a window of at most 18 months;
  a window that contains the true date but spans more than three years is
  scored `vague`, and the median window width is reported next to the hit rate.
- **Birth time honesty.** Every public figure's birth TIME is unverified, so
  those profiles are created with `time_known: false`. `run_eval.time_sensitivity()`
  measures, for free, how far the dasha boundaries move between a 00:01 and a
  23:59 birth on the same date — that number is the ceiling on what a
  birth-time-unknown chart can be blamed for.
- **Every automatic flag was read by hand.** Both grounding checkers produce
  false positives (a sentence about rulership looks like a placement; a Yogini
  period looks like a Vimshottari one). The verdicts are in `manual_review.json`
  and the report prints machine-flagged and hand-confirmed counts separately.
- **Resumable and capped.** Answers are appended to `out/answers.jsonl` as they
  arrive, spend already on disk counts against `--budget`, and the run aborts
  itself at the cap. Delete `out/` to start over; keep it to continue.

## Re-running

Safe to re-run: it reuses the `Client A`..`Client H` profiles if they already
exist and skips any question already in `out/answers.jsonl`. To re-ask one
question, delete its line from `out/answers.jsonl` and its line from
`out/scores.jsonl`.

`--limit N` asks at most N new questions, which is the cheap way to smoke-test
a change to the harness.

## Credentials

- `EVAL_API_BASE` (default: the Cloud Run URL), `EVAL_TOKEN_FILE` (default
  `/tmp/eval_token.txt`) — an app JWT for a funded test user.
- The judge key is read from `deploy/gcp/terraform/terraform.tfvars`
  (`anthropic_api_key`). Nothing here prints or logs a key.
- Firestore reads use `gcloud auth print-access-token` against project
  `$PROJECT_ID`, read-only.
