# Ablation plan and dev subset (GEM-12)

Status: plan from 2026-11-09, updated 2026-11-12 with what has run (table below). Aggregates only.

## What has run (36 dev tasks, resolved per replicate)

| Arm | Model | Resolved | Where | Row in `QUESTIONS.md` |
|---|---|---|---|---|
| A0 baseline | 31B | 13, 15 | Kaggle 4 x L4 | A40 |
| A2 localizer skill | 31B | 14, 14 | Kaggle 4 x L4 | A40 |
| A4 run-a-test prompt (`tests_v1`) | 31B | 15 (one replicate) | RunPod L40S | A41 |
| baseline prompt | E4B | 5 (one replicate) | RunPod RTX 2000 Ada | A43 |
| baseline prompt | E2B | 6 (one replicate) | RunPod RTX 2000 Ada | A43 |

Not yet run: A1, A1b (graph tools), A5 to A7 (prompt bundles), B, C, D. Failure analysis of these runs:
`docs/FAILURE_ANALYSIS.md` (A42): gold-patch size separates solved from never-solved tasks; only the 8
flaky tasks leave room for a prompt change to beat noise.

## Dev subset

`python -m analysis.dev_subset` writes `data/dev_subset.json` (gitignored; the rule and seed
regenerate it). The rule:

- rich is held out. Winners are confirmed there (GEM-33), never tuned on it.
- Tasks whose baseline test run was inconclusive are dropped (9 of 30 baseline tasks, GEM-16), and so
  are tasks whose test patch mentions `inline_snapshot`, `dirty_equals`, `httpbin` or `trustme`
  (29 of 129 public tasks, A39). The public grading image lacks them, so these tasks carry no signal
  in our runs.
- A seeded draw per repo: fastapi 30, requests 5, httpx 1. Total 36 tasks.
- Every arm runs the same 36 tasks, so arms are compared pairwise.

Cost: about 5.3 min per task, so about 3.3 h of GPU per arm and replicate.

## What 36 tasks can detect

From `dashboards/noise.py` (binomial plus a task-mix term): with 3 replicates per arm, a gain of
about 8 to 9 points is detectable at 5% significance and 80% power. A 5-point gain needs about 8
replicates. So on the real set we can only confirm large effects, and each arm costs 10 h of GPU for
3 replicates. This is the case for the synthetic proxy (`docs/SYNTHETIC_DATASET.md`): screen many
variants cheaply there, run only finalists here.

## Arms

| Id | Arm | Lever | Card |
|---|---|---|---|
| A0 | Baseline bundle (graph tools banned by prompt) | none | GEM-10 |
| A1 | Same, prompt allows graph tools (`experiments/bundles/graph_v1`) | prompt | GEM-13 |
| A1b | A1 plus a note that the graph has no async, test or docs_src nodes (`graph_blind_v1`) | prompt | GEM-68 |
| A4 | Baseline plus a required targeted-test step (`tests_v1`) | prompt | GEM-31 |
| A5 | Counted call plan: first edit by call 5 (`first_edit_v1`) | prompt | GEM-29 |
| A6 | Concrete edit_file retry steps keyed on the real error text (`edit_retry_v1`) | prompt | GEM-30 |
| A7 | One-line stated doubt before each tool call (`doubt_v1`) | prompt | GEM-32 |
| A8 | E2B: 33% shorter prompt, edit copy rule and retry recipe, submit-tool rule, reasoning cap (`e2b_v2`; baseline is `e2b_v1`; six numbered changes in `docs/SMALL_MODEL_FAILURES.md`) | prompt | GEM-36 |
| A9 | E4B: edit copy rule and retry recipe, no submit on a failing test, spare-call diff check, submit-tool rule (`e4b_v2`; baseline is `e4b_v1`) | prompt | GEM-36 |
| A2 | Localizer skill, one call returns top 10 | skill | GEM-80, 82 |
| A3 | A2 plus co-change suggestions | skill | GEM-81 |
| B1 | Tool-call limit 28 vs 40 | limits | GEM-14 |
| B2 | Time limit 8 vs 12 min | limits | GEM-14 |
| C1 | thinking_budget 0, 2048, 4096 (baseline), 8192 | thinking | GEM-15 |
| C2 | temperature 0.2 (baseline) vs 0.6 | sampling | GEM-15 |
| D1 | Planner then editor (SequentialAgent) | workflow | later |
| D2 | Edit then test, Loop up to 3 | workflow | later |
| D3 | Prompt variants: locate-then-edit, recovery, test selection | prompt | GEM-29 to 32 |

The competition-wide 12 h limit is about 6 min per task if tasks run one at a time, so B2 above 8
min and any workflow agent that adds model calls must be judged against the 12 h projection
(GEM-34), not only against the pass rate.

## Order and rules

1. ~~Run A0 twice more to get our own replicate spread.~~ Done: A0 has two replicates (13, 15), the spread is about 2 tasks.
2. Screen A1, A2, A3 with 2 replicates. Drop arms that are not above A0 by the spread.
3. Screen B, C and D arms on the synthetic set once its validity check passes. Until then, run
   only the arms the paper needs.
4. Run finalists with 3+ replicates on the dev subset, then once on rich.
5. Report every arm with its spread, its failure classes (`analysis/failure_classes.py`) and its
   minutes per task. A gain smaller than the detectable gain is reported as "not resolved".

## Open

- Whether the grader has the same missing-module and `httpbin` gaps as our sandbox (A39). Kaggle's subprocess
  image and the official Docker grader may use different package versions (`docs/GPU_RUNS.md`, section 10).
- GPU access: Kaggle's weekly quota is about 15 h of L4x4, so replicates also run on RunPod (`docs/GPU_RUNS.md`,
  "How we run a pod today"). A pod's GPU differs from the leaderboard's, and the 8-minute limit is wall-clock time,
  so compare timeouts across hardware with care.
- The small-model track (E4B, E2B) is where tuning is cheapest: about 0.5 USD per replicate on a 16 GB card.
