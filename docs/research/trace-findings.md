# T1 findings: what the existing 31B traces say (2026-11-13)

Data: four 31B runs on the 36 dev tasks (dev-a0-r1/r2 baseline, dev-a2-r1/r2 skill arm; 144 task-runs, 56 resolved).
A fifth set (30-task baseline, 3 resolved) is too small to add to the pooled numbers. Code: `analysis/trace_questions.py`
(`uv run python -m analysis.trace_questions data/runs/<run>`). Aggregates only (rules 4b). The skill arm made no difference to
resolution (A40), so pooling the runs is reasonable for behaviour questions.

## Q1. Chat-template symptom (reasoning lost after the first tool call): inconclusive

- Traces do not store the model's thinking (1,009 agent steps in dev-a0-r1; 10 mention "thought"), so the question cannot be
  answered directly for 31B. The small-model console logs do have thought length, but they are E4B/E2B, not the 31B in the bug report.
- Visible text per step: median about 520 to 580 characters at call 1 (the plan), then 110 to 270 from call 2 on, in all five runs. It
  is never empty: 0 to 1% of steps after the first have no text. So the agent keeps commenting after the first call. That argues
  against the worst form of the bug but says nothing about hidden reasoning.
- Next if we want an answer: a probe on the pod with a small model that logs the raw completion before and after the first tool result
  (needs GPU time, about 0.1 USD). Low priority until a symptom shows up.

## Q2. After a refused edit (31B): it rarely retries blindly

45 refused `edit_file` calls over the four runs (6 to 16 per run). The next call was:

| Next call | Count | Share |
|---|---|---|
| Re-read the same file | 14 | 31% |
| `edit_file` on the same path again | 5 | 11% |
| Something else (test, search, other file) | 25 | 56% |
| Nothing (refusal was the last call) | 1 | 2% |

So 31B mostly moves on rather than loops. The "something else" bucket is the big one and is not broken down yet (does the edit ever
land later? Is it a different edit?). E4B/E2B have no traces here, so the same split for them needs the v3 run (T4), where we should
capture traces, not only the console log.

## Q3. Timing: edit early, but calls are not the lever

- Resolved task-runs reach their first edit at median call 6.5 to 8 (70 to 105 s). Unresolved ones at median call 15.5 to 20 (170 to 190 s).
- Share resolved by first-edit call (all 144 task-runs): before call 10, 40 of 60 (67%); call 10 or later, 16 of 84 (19%). Before call 6: 22 of 32 (69%).
- Four task-runs never edited; none resolved.
- **A call cap would cost resolutions.** Resolved runs submit at median call 22, 75th percentile 28. A cap at 20 would have cut 37 of 56 resolved
  task-runs (the recorded call count includes calls the harness refused after the budget, so the exact number is a little inflated, but the median is not near 20).
  Dropping T6 as a call-cap rule.
- **Confound, and a partial check.** Early first edits may only mark easy tasks. Within the 5 flaky tasks (solved in some of the four runs, not all),
  the resolved replicate edited earlier in 4 of 5, by a median of 6.5 calls. The first-edit call for the same task varies a lot between replicates
  (median spread of 8 calls over the 36 tasks), so it is not fixed by the task. n = 5: a lead, not proof.

Reading: the baseline prompt already says to edit by call 12. Runs where the agent ignores that are the ones that fail; whether a stronger
nudge helps, or whether the late editors are simply on hard tasks, needs an A/B with a log signal (first-edit call), not resolution alone.

## Q4. Flaky tasks

Across the four runs: 12 tasks always resolved, 5 flaky, 19 never (A42 counted 8 flaky over five runs). Only Q3's within-task check was
run; nothing else separates the 5 flaky tasks at this n.

## What this changes in the task list

- T2 stays inconclusive; T6 answered (no call cap). New candidate T13: a prompt A/B that moves the first edit earlier (log signal: first-edit call, edit refusals, resolution as a side note).
- T3 (edit-failure taxonomy) is still open and now matters mostly for E4B/E2B, not 31B.
