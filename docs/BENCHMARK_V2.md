# Benchmark v2: a synthetic task set that can rank agents and feed training (design, 2026-11-15)

Builds on `docs/SYNTHETIC_DATASET.md` (stages 1 to 2c: mutants, runnable export, multi-site). Aggregates
only; nothing here comes from per-task competition data. Numbers marked [estimate] are arithmetic, not runs.

## Why v1 is not enough

- **Too easy and too local.** Operator mutants change 2 lines per site. Public gold patches change a median
  of 12 library lines (p25 4, p75 44, p90 127) over a median of 2 hunks, measured on the 129 public tasks.
  Mutants with up to 5 sites reach 10 lines, so they cover the bottom third and miss the half that
  decides the score (A42: tasks over 10 lines resolve 11% of the time).
- **Never validated.** The stage-3 rank test needs 6 variants and about 6 replicates on both sets. On this
  GPU that is weeks.
- **Only 9 repos pass readiness**, and the sandbox stack has only some test dependencies.

## What it must do

1. **Screen** E4B/E2B agent changes (prompts, sampling, skill scripts, loops) with a power we do not have on 36 tasks.
2. **Supply training data** (self-distilled traces, optionally teacher traces) for a LoRA, split by repo so
   evaluation tasks never appear in training.

## Power: why size matters more than replicates [estimate]

Replicates average out sampling noise inside a task. The floor is task-to-task flipping: A40 saw about 4 of 36
tasks (11%) flip between replicates. For a paired comparison on N tasks, one replicate each, the smallest
difference detected at 80% power and 5% significance is about 2.8 x sqrt(0.11 / N):

| N tasks | 36 | 100 | 150 | 200 | 300 |
|---|---|---|---|---|---|
| detectable gap (points) | 15.5 | 9.3 | 7.6 | 6.6 | 5.4 |

So a 150-task screen sees an 8-point effect, a 300-task one a 5-point effect. At the measured 2.4 to 3.3 min
per E4B task that is 6 to 8 h (150) or 12 to 16 h (300) per arm. Two consequences: (a) use log signals
(first edit call, edit refusals, calls per task, timeouts), which move with far less noise, as the first
readout, and (b) get throughput from concurrency (below).

## Task sources, in order of realism

| Source | What | Difficulty it reaches | Needs |
|---|---|---|---|
| S1 Real commits | For each admitted repo, walk git history: commits that change library and test files, where the new tests fail on the parent and pass on the commit. Base = parent, `test_patch` = the commit's test changes, `patch` = library part. Issue text written from the commit message (never the diff) | The real size distribution, real bug kinds | Full clone (v1 fetch is `--depth 1`); the commit's dependencies must exist in the sandbox image |
| S2 Model-made bugs | A model rewrites one function or a pair to inject a plausible bug (SWE-smith style); kept if tests fail before and pass after the inverse patch | 5 to 40 lines, semantic bugs | A model on the GPU queue; leak checks |
| S3 Operator mutants | Stage 2b/2c as built | 2 to 10 lines | Nothing new. Kept as the cheap control |

Target mix: match the public gold-size histogram bin by bin (<=4, 5 to 12, 13 to 44, over 44 lines), by
reweighting or subsampling, and report the distance. Do not claim a bin we cannot reach (the over-44 bin
will come from S1 only).

## Repo pool

Admit a repo when every module its tests import is installed in the sandbox image. The image is the
competition's test stack (`docker/synthetic/requirements.txt`, mirrors `pod/test_env.sh`: pytest, anyio,
httpx, starlette, fastapi, pydantic, Jinja2, SQLAlchemy, Flask, Werkzeug, click, typer, rich, requests,
PyYAML and their dependencies; no tqdm, hypothesis, freezegun or pytest-asyncio). `synthetic/sandbox_modules.txt`
lists what it can import, and `python -m synthetic.readiness CACHE --installed synthetic/sandbox_modules.txt`
applies the rule. A repo's declared runtime dependencies must be installed too. Hold out whole repos for
evaluation (train repos and eval repos never overlap).

## Realism checks (before any agent run)

Computed on the public set, aggregates only, and compared with the synthetic set:
gold lines and hunks quantiles, files per patch, share of async targets, issue length (median 58 words), BM25
hit@10 (public 55%, accept 45 to 65%), name-leak rate near 20%.

## Validity, cheaper than the v1 rule

The v1 rule (6 variants x 6 replicates on both sets) stays for finalists once Kaggle quota returns. Now:

1. **Behavioural fingerprint.** Run E4B v2 on 100 synthetic tasks and compare log signals with the existing
   real-dev E4B runs: edit refusal rate (39% baseline), median calls (9), first-edit call, time-out share,
   share of tasks that run a test. Pass: each within a band we fix before looking (proposal: relative
   difference under 30%). Free apart from the run.
2. **Dose-response ladder.** Degrade one thing in known steps and require monotone resolution on both sets:
   tool-call cap 6, 10, 16, 28; E2B against E4B. Large effects, so detectable at 100 to 150 tasks.
3. **Replicate agreement.** Two replicates of one arm: flip rate should be near the real 11%. Much higher
   means the tasks are noise, much lower means they are too easy.

If 1 and 2 fail, the set serves training data and localization only, and we say so.

## Throughput

`EVAL_CONCURRENCY` (default 1) exists in `kaggle/build_kernel.py`. At concurrency 1, GPU use was a median 40%
(p90 98%) with one running request, so decode is memory-bound and parallel tasks should add throughput.
Caveat: the 480 s limit is wall clock, so concurrency changes timeouts; every arm in a comparison must use the
same N, and numbers are not comparable with earlier concurrency-1 runs. Probe first: 12 tasks at N = 1, 2, 4,
reading tokens per second, timeouts and VRAM (`gpu_samples.csv`, `SUSPECT_VRAM`).

## Training data

- Self-distillation first: sample E4B k times per task, keep resolved runs (and failure-then-recovery
  segments), split by repo.
- Teacher traces (Claude or another hosted model): allowed for this competition by the owner (A50, 2026-11-16),
  for the Rules tab and the provider's terms. Only synthetic, non-competition tasks ever go to a hosted API
  (rules 4b); real task text, patches and traces stay local.
- A LoRA must be trained on the bf16 base and served on the w4a16 base; check the quality gap before relying on it.

## Slices and gates

| Slice | Output | Gate |
|---|---|---|
| B0 Concurrency probe | tokens/s and timeouts at N = 1, 2, 4 on 12 existing dev tasks | Pick N with under 10% extra timeouts |
| B1 Pool and S3 at scale | Readiness against the sandbox stack, 8+ repos, 300 mutant tasks | Realism checks pass (size gate fails for S3: see B1 result) |
| B2 S1 miner | Real-commit tasks from the pool, verified twice in Docker | 100+ tasks, size histogram reported (done: 162 tasks, distance 0.158) |
| B3 Issue text | Model-written text with leak checks | BM25 and leak gates |
| B4 Validity | Fingerprint, ladder, replicate agreement | Pass or declare training-only |
| B5 Training data | Self-distilled traces, repo-split | Needs B4 or accepted as training-only |

## B1 result (2026-11-16): pool and operator mutants

- **Pool.** Of the 23 manifest repos the rule admits 10: click, typer, markdown-it-py, mistune, cachetools,
  sqlparse, toolz, more-itertools, sortedcontainers, tomli. The old stdlib-only rule admitted 9 (toolz is new).
  The stack is too small to admit the web repos (starlette, werkzeug, flask need trio, watchdog and
  test-local modules) or ones that need hypothesis or freezegun. Adding those packages to our image would
  widen the pool but make the agent's own test runs differ from the competition's, so we did not.
- **Typer fails the baseline.** It is admitted statically, but only 72.5% of its own tests pass in the image,
  so the mutant build rejected it. Static admission is necessary, not sufficient.
- **S3 at scale.** 60 mutants per repo over the 9 other repos gave 251 tasks (click 19, markdown-it-py 18,
  mistune 14, cachetools 21, sqlparse 27, toolz 40, more-itertools 41, sortedcontainers 29, tomli 42), all
  verified end to end. This misses the 300 target; 110 mutants per repo would reach it. The run took 2.4 h
  of CPU containers (more-itertools alone 76 min).
- **Realism, against the 129 public tasks (`python -m synthetic.realism`).** Gold size fails the gate:
  every mutant task has 2 gold lines (public median 12, p25 4, p90 128), so the histogram distance over
  the four size bins is 0.68 (0 = same, 1 = disjoint). Public bins: 32% <=4 lines, 19% 5 to 12, 24% 13 to 44,
  25% over 44; mutants put 100% in the first. Issue length matches (median 58 words) because the
  generator is templated, which says nothing about realism. S3 stays the cheap control; the middle and large
  bins have to come from S1.

## B2 result (2026-11-16): real-commit tasks (S1)

`python -m synthetic.mine HISTORY_DIR NAME [NAME ...] [--max-commits N] [--out DIR]` clones each repo with full
history (only `git` runs on it), takes the newest single-parent commits that change both library and test
`.py` files, builds a task from each (base = parent, `patch` = library part, `test_patch` = test part, issue
= the commit message without PR numbers, links and trailers) and verifies it in the no-network container:
the touched test files run twice on the parent plus the new tests and twice on the commit. A commit is kept
when some test fails before and passes after, the same set both times.

- **Yield.** 30 newest candidate commits per repo (all 16 for tomli; 15 for click) over 10 repos gave 162
  verified tasks: click 10, cachetools 20, sqlparse 25, typer 20, markdown-it-py 8, mistune 28, toolz 12,
  more-itertools 26, sortedcontainers 4, tomli 9. 162 of 271 candidates tried (60%) are usable. Where
  commits are dropped: no fail-to-pass test (most often; markdown-it-py 20 of 30, sortedcontainers 21 of 30,
  toolz 17 of 30), 14 with a patch outside 1 to 300 lines, one time-out, one deleted test file. The yield per repo
  is limited by the test-only or docs-only commits, not by the sandbox's package versions.
- **Realism (`python -m synthetic.realism`).** Gold lines median 10.5 (public 12), p25 5 (4), p90 75 (128);
  hunks median 2 (2), files 1 (1); size bins 22/34/25/19% against 32/19/24/25% public. Histogram distance
  0.158, against 0.68 for the mutants. The bins over 44 lines are filled from real commits but the tail
  is shorter (p90 75 vs 128).
- **Gaps.** Async: none of the 162 touch async code (public 9%). Issue text: commit messages have a median
  of 9 words (public 58), so B3 must write the issue text; until then S1 tasks are not comparable on the
  issue side. Tasks come from the 10 admitted repos only, and from the newest commits, so they use
  APIs close to the pinned release.
- **Not checked.** Behavioural fingerprint (slice B4), leak rate of function names in the commit messages,
  and whether the miner's tasks resolve at a rate like the real ones.

## Open questions

- Do old commits run with the sandbox's installed dependency versions? S1 yield depends on it.
- Is the competition's grading image a superset of the sandbox stack? (A39, GEM-94.)
- Does concurrency change E4B behaviour beyond timing (it should not, but measure)?
