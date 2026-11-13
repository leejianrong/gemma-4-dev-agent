# T1: zero-GPU trace analyses (spec)

Goal: answer four questions from data we already hold, with aggregates only (rules 4b: no task ids, text or patches in the repo).

## What we have locally (`data/runs/`, gitignored)

| Source | Runs | Content |
|---|---|---|
| ATIF traces `raw/traces/trace_<id>.json` | 31B: dev-a0-r1/r2, dev-a2-r1/r2 (36 each), gemma-4-eval-runner (30) | Per step: agent `message` (visible text, median about 400 chars), one tool call, observation, `metrics.prompt_tokens`, `extra.elapsed_s` |
| Console logs `job.log` | E4B, E2B, v2 runs, a3 pod run (no traces) | Event lines with elapsed time, tool calls, thought length in characters |

Checked 2026-11-13 on dev-a0-r1: 1,009 agent steps, only 10 mention "thought" and 4 a channel marker, so **traces do not
record the model's reasoning**. Thought length exists only in the small-model console logs. `analysis/trace_review.py` and
`analysis/small_model_log.py` already read both formats; extend them rather than adding a third reader.

## Questions

**Q1. Does reasoning (or any commentary) shrink after the first tool call? (chat-template bug, literature.md section 2)**
- 31B traces: agent `message` length by step index (step 1, 2, 3, then later), share of steps with an empty message.
- Small-model logs: thought characters by call index.
- Expect, if the bug is live: a sharp drop after call 1 and a long flat tail. Compare resolved against unresolved tasks.
- Limit: message length is a weak proxy for thinking. A drop is a lead, not proof.

**Q2. What do edit failures look like, and what comes next? (literature.md section 1, A44)**
- Per run: `edit_file` calls, refusals by kind, and the next action after a refusal (re-read the file, retry the same string, give up, switch to `write_file`).
- Rate of a second refusal straight after a first, and whether the string differed.
- Aggregate only. The v3 run later reuses the same code to compare.

**Q3. Where does the time go, and could it move? (literature.md section 3, A42)**
- Per task-run: seconds and calls to the first edit, to the first test, to submit. Budget stops and time-outs by outcome.
- For tasks that resolved: how many calls and seconds they actually needed (distribution). If solved tasks mostly finish by call 15, a cap at call 20 costs little and frees time; if they use calls 25 to 28, it does not.
- For flaky tasks (solved in some replicates): did the failing replicate run out of budget or finish wrong?

**Q4. What separates flaky tasks across replicates? (A42: flaky and `broke_code` are where a prompt could still matter)**
- Same task, resolved in one replicate and not another: differences in first edit position, number of edits, tests run, calls used.
- Four 31B runs, 8 flaky tasks: tiny n; report as description, no tests.

## Output

- One script `analysis/trace_questions.py` (extends `trace_review`), printing aggregates.
- `docs/research/trace-findings.md` with tables, a one-line verdict per question, and the numbers' source run ids.
- New A-row in `docs/QUESTIONS.md` only for what is solid. Anything inside the noise is labelled so.
- Failing test first for each new reducer, on a synthetic trace (see `tests/` for the existing trace_review fixtures).

## Not in scope

No GPU, no network, no code from the tasks run on the host (we only parse JSON). No claim that a trace feature causes resolution.
