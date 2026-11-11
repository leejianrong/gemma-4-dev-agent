# Ablation plan and dev subset (GEM-12)

Status: plan, 2026-11-09. Nothing in it has been run on agents yet.

## Dev subset

`python -m analysis.dev_subset` writes `data/dev_subset.json` (gitignored; the rule and seed
regenerate it). The rule:

- rich is held out. Winners are confirmed there (GEM-33), never tuned on it.
- Tasks whose baseline test run was inconclusive are dropped (9 of 30 baseline tasks, GEM-16), and so
  are tasks whose test patch mentions `inline_snapshot`, `dirty_equals`, `httpbin` or `trustme`
  (29 of 129 public tasks, A39). The public grading image lacks them, so these tasks carry no signal
  in our runs.
- A seeded draw per repo: fastapi 30, requests 5, httpx 1. Total 36 tasks.
- Every arm runs the same 37 tasks, so arms are compared pairwise.

Cost: about 5.3 min per task, so about 3.3 h of GPU per arm and replicate.

## What 37 tasks can detect

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

1. Run A0 twice more to get our own replicate spread. We only have one run of it.
2. Screen A1, A2, A3 with 2 replicates. Drop arms that are not above A0 by the spread.
3. Screen B, C and D arms on the synthetic set once its validity check passes. Until then, run
   only the arms the paper needs.
4. Run finalists with 3+ replicates on the dev subset, then once on rich.
5. Report every arm with its spread, its failure classes (`analysis/failure_classes.py`) and its
   minutes per task. A gain smaller than the detectable gain is reported as "not resolved".

## Open

- Whether the grader has the same missing-module and `httpbin` gaps as our sandbox. If it does,
  the 6 requests tasks in the dev subset are risky. A gold-patch run would settle it.
- Kaggle GPU queue time. If it stays long, move replicate runs to a pod (A100 at about 1.39 USD/h);
  the eval runner has never run on a pod, so budget one debug run.
