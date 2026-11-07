# Gemma 4 Developer Agent: Slices

Vertical increments, each ending in a demonstrable result. V1 confronts the riskiest unknown: whether a 31B submission starts and finishes on Kaggle at all.

## V1: Reproduce the baseline on Kaggle

**Delivers:** R1, R2, R3, R0 (reference point)

**Build plan**

1. Replace the placeholder `submission/` with the budget-aware bundle (attribution kept), adapted to the file layout in `HARNESS_README.md`; `make check` passes.
2. Write the eval-runner kernel (`kaggle/eval_runner.py` plus `kernel-metadata.json`), based on the starter notebook's Evaluator calls: unpack zip, run `adk_submission.validate_directory`, start vLLM, run Phase 1 and 2 on a named subset with concurrency, write `summary.json`. Kaggle notebooks have no Docker daemon, so expect the subprocess sandbox; confirm in the first smoke run.
3. Push it with `kaggle kernels push`, attached to the competition and the 31B model, L4x4, internet off.
4. Run a small smoke subset (5 tasks), then ~30 tasks stratified by repo; append rows to `experiments/runs.csv` with a script.
5. Upload the zip as one leaderboard submission.

**Demo:** the kernel log shows the server healthy, tasks resolved/timed out, and `runs.csv` gains a row with minutes per task; the leaderboard shows a score near 0.17.

**Rests on assumptions:** A14 (limits fit 12h at scoring concurrency), A19 (31B starts); if wrong, lower the budget or fall back to 12B.

### Test plan

#### End-to-end
- The kernel completes the 30-task subset without a server-health failure and writes `summary.json`.
- `runs.csv` has a row whose zip hash equals `sha256(dist/submission.zip)`.
- Leaderboard score for the zip is within 3 tasks of ~0.17, or the gap is explained in `runs.csv` notes.
- Projected full-run time (median minutes per task × tasks ÷ concurrency) is under 12h.

#### Integration
- `kaggle kernels push` succeeds and the kernel finds the competition data and 31B model paths.
- `validate_directory` accepts the zip inside the kernel.

#### Unit
- The `runs.csv` appender rejects a row without a zip hash and writes columns in a fixed order.
- Pre-flight tests still pass (`make check`).

## V2: Ablation matrix and failure taxonomy

**Delivers:** R3, R0, R5 (small-model data)

**Build plan**

1. Define variants, one change each: graph tools off vs on; budget (28/8 vs 40/6 vs 28/12); thinking budget (4096 vs 0 vs 8192); E4B and E2B with the baseline prompt.
2. Run variants in priority order (graph tools, budget, E4B, thinking, E2B), each twice on the same ~30-task subset (replicates), including the held-out repo. The full matrix is too big for the 4 days before the paper deadline: the paper uses whatever has finished by Nov 11, and the rest continues for M2.
3. Classify each failed task from traces: timeout, tool-budget stop, empty patch, patch fails to apply, wrong fix.
4. Add `make report` that renders `runs.csv` into a table and a per-variant failure chart.

**Demo:** `make report` prints a table of variants with mean resolved ± spread and failure-class counts.

**Rests on assumptions:** A17, A18; if noise exceeds ±3 tasks, increase replicates before drawing conclusions.

### Test plan

#### End-to-end
- Every variant has two rows in `runs.csv` and the report shows both and their spread.
- The report names at least one variant that beats the baseline mean, or states that none does.
- Every failed task in the matrix has exactly one failure class.

#### Integration
- Report generation reads only `runs.csv` and traces; it produces identical output on re-run.

#### Unit
- The failure classifier maps fixture traces (timeout, empty patch, budget stop) to the right class.

## V3: Paper v0 (deadline 2026-11-12)

**Delivers:** R4

**Build plan**

1. Owner joins the paper-track competition and accepts its rules; create the Kaggle Writeup draft early so the submit button is available.
2. Write `paper/` (<=3,000 words: title, subtitle, abstract, introduction, methods and experiments, related work with citations) from V1/V2 rows: graph-tools on/off with replicates, budget and model-size context, failure taxonomy, limitations (noise, small set, third-party baseline). Attach a public notebook with the exact config, prompts and zip hashes.
3. Every number cites a `runs.csv` row; add a check that fails on an uncited number.
4. Submit on Kaggle before the deadline.

**Demo:** the paper is submitted on the Kaggle paper-track page and the repo contains the exact source.

**Rests on assumptions:** V1 and V2 data exists by Nov 11, otherwise the paper reports V1 plus a smaller ablation.

### Test plan

#### End-to-end
- Submission confirmation is visible on the Kaggle paper track before 2026-11-12 23:59 UTC (a saved draft does not count).
- The word count is <=3,000 and all five required sections are present.
- Every table value in the paper matches `runs.csv`.

#### Integration
- `make paper-check` fails if a number in the paper has no run id.

#### Unit
- The citation checker flags an uncited number and accepts a cited one.

## V4: Beat the baseline (31B)

**Delivers:** R0, R1, R2

**Build plan**

1. Take the V2 winners and try the next ideas one at a time: tighter locate-then-edit schedule, edit-recovery on exact-match failures, targeted-test selection, an uncertainty-before-tool-call prompt.
2. Run each candidate with replicates; keep only changes that win by ≥3 tasks on the held-out repo and do not lose on the rest.
3. Freeze a candidate by 2026-11-28 and use leaderboard submissions sparingly.

**Demo:** the best 31B zip beats the V1 baseline by ≥3 tasks on the held-out repo in replicated runs, with a public leaderboard score to match.

**Rests on assumptions:** A18; leaderboard variation may hide small real gains.

### Test plan

#### End-to-end
- Best-vs-baseline difference on held-out repo ≥3 tasks across two replicates.
- Full-run projection stays under 10h (2h margin).
- Public leaderboard score of the frozen zip is at least the V1 baseline score.

#### Integration
- The frozen zip passes `validate_directory` in the kernel.

#### Unit
- Pre-flight tests cover any new file type or config field introduced.

## V5: Small-model entry (E4B or E2B)

**Delivers:** R5

**Build plan**

1. From V2 data, choose E4B or E2B; tune prompt and budget for the smaller context behaviour.
2. Replicate on the held-out repo; compare with its V2 row.
3. Submit and tag it as the second final submission.

**Demo:** a leaderboard entry using the small model, listed as eligible for the bonus.

**Rests on assumptions:** the small model resolves at least a few tasks; if it resolves none, report that in the paper and skip the bonus.

### Test plan

#### End-to-end
- The zip declares exactly the chosen small model and passes pre-flight.
- Leaderboard shows a scored entry for it before the final deadline.

#### Integration
- `validate_directory` accepts it in the kernel.

#### Unit
- A test that a submission mixing 31B and a small model fails pre-flight (already covered; keep).

## V6: Advanced methods spike (M3, under the $10 cap)

**Delivers:** R7

**Build plan**

1. Collect successful trajectories from V2/V4 runs (rejection sampling from the model itself).
2. Train a small LoRA (rank ≤16) on E2B or E4B with SFT on a rented RunPod pod using the `runpod-jobs` skill with a dead-man's switch; hard stop at $10 total.
3. Evaluate the adapter inside the same runner; compare with its no-adapter row.
4. Write up RL, distillation, quantization and pruning as what was studied and what is not shippable under the rules.

**Demo:** a `runs.csv` row for a LoRA submission next to its no-adapter twin, plus the pod's total cost.

**Rests on assumptions:** enough successful trajectories exist; if fewer than ~20, stop and say so.

### Test plan

#### End-to-end
- The adapter zip passes pre-flight and `validate_directory` and runs a full subset.
- Total RunPod spend is recorded and ≤ $10.

#### Integration
- Pod teardown is confirmed (no running pods) after every job.

#### Unit
- Pre-flight rejects an adapter missing `adapter_model.safetensors` (already covered).
