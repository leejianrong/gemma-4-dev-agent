# Gemma 4 Developer Agent: Plan

Status: agreed (2026-11-07) · Milestone: M1 = reproduce + ablate + paper (Nov 12); M2 = beat baseline + two final submissions (Dec 2); M3 = advanced methods (open-ended)

## Problem

Kaggle scores an offline Gemma 4 agent on hidden SWE-style tasks (~120, private repos): pass rate of hidden pytest tests. The sample submission scores ~0.06–0.08 on the public leaderboard because its budget is 1 minute and 10 tool calls. Public notebooks that raise the budget and add a call-plan prompt reach ~0.17–0.18, with claims up to ~0.24. The public leaderboard has ~58 tasks, so one task is ~1.7 points and identical zips reportedly vary by ~2 tasks. Progress is hard to see without a disciplined way to measure it.

## Solution

A repo that builds `submission/` (YAML config, prompts, optional LoRA), packages and pre-flights it, runs it on Kaggle's L4x4 against the public tasks, and records every run in one table. Two outputs: final submissions for the leaderboard (a 31B entry and an E4B/E2B entry for the $10k bonus), and a short paper on what actually moved the score for a small offline agent.

## Users and actors

- **The Kaggle grader** (primary): consumes only `submission.zip`. It wins every conflict.
- **The owner**: runs experiments, decides forks, submits. Has no local GPU.
- **Coding agents** working in this repo, following `CLAUDE.md`.
- **CI**: lint, unit tests, secret scan, submission pre-flight.

## Scope

**In M1/M2.**
- Reproduce the budget-aware baseline (ADR-0005) and confirm 31B starts and finishes inside the limits.
- A run table and eval runner (Kaggle kernel) with a fixed protocol.
- Ablations: graph tools on/off, budget and call-plan variants, thinking budget, E4B/E2B vs 31B.
- Short paper by 2026-11-12; two final submissions by 2026-12-02.

**Out.**
- Training of any kind before the baseline reproduces (M3, ADR-0002).
- Mixing models in one submission (forbidden by the rules).
- Paid compute beyond the $10 RunPod cap (ADR-0004).
- Base-model quantization or pruning as submitted artifacts: only the four `w4a16-ct` bases and `.safetensors` LoRA adapters are allowed, so these can only be studied, not shipped.
- Repo-specific prompt tricks: the hidden set is private repos.

## Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | Beat the reproduced baseline by ≥3 tasks on a held-out repo, then on the public leaderboard | Core goal |
| R1 | Every submission zip passes local pre-flight and Kaggle `validate_directory` before upload | Must-have |
| R2 | A full run finishes in under 12h with measured margin | Must-have |
| R3 | Every run is recorded (config hash, model, subset, resolved, timeouts, minutes per task) | Must-have |
| R4 | Kaggle Writeup (<=3,000 words) submitted to the paper track by 2026-11-12 23:59 UTC, with a public notebook | Must-have |
| R5 | One of the two final submissions uses E4B or E2B | Must-have |
| R6 | No secrets, data, zips or weights in git | Must-have |
| R7 | LoRA/SFT/RL/distillation experiments within the $10 cap | Nice-to-have |

## Shape

| Part | Mechanism | ADR |
|------|-----------|-----|
| S1 | `submission/` is the only deliverable; `scripts/submission.py` pre-flights and zips it deterministically | 0005 |
| S2 | Eval runner: a Kaggle kernel that unpacks the zip, runs `swegemma eval` on a named task subset with concurrency, and writes `summary.json` plus traces | 0004 |
| S3 | Run table `experiments/runs.csv`, one row per run, committed; raw results stay out of git | 0005 |
| S4 | Ablation matrix: each variant changes one thing from the baseline; model, sampling and limits stay fixed unless they are the variable | 0005 |
| S5 | Paper: `paper/` Markdown built from `runs.csv`, nothing claimed without a row; question: do code graphs/embeddings help a small agent. Optional released resource: labelled trajectories + run table | 0006 |
| S6 | Finals: best 31B zip and best small-model zip, both tagged in git with their score | 0003 |

## Implementation decisions

- Identity of an experiment is the SHA-256 of the zip. Two runs of the same hash are replicates.
- Dev protocol: 129 public tasks split by repo (hold out one repo). Judge a change only on replicated runs; treat differences under 3 tasks as noise (A18).
- Config limits start from the best public values (8 min, 28 calls, 240 s command timeout, 80 turns) and move only from measured throughput.
- The baseline prompt keeps the original attribution (Apache-2.0).
- Local machine: editing, packaging, CI. All inference on Kaggle.

## Testing approach

Fast tests cover packaging and pre-flight only (they already exist). Everything model-dependent is checked by runs, not unit tests: the acceptance criteria in SLICES.md are run-table rows. A guard test is proven by breaking what it protects before it is trusted.

## Assumed defaults

See `docs/QUESTIONS.md` A1–A20. Load-bearing ones:

| ID | Assumed | Cost if wrong |
|----|---------|---------------|
| A14 | 8 min / 28 calls fits 12h at scoring concurrency | Timeouts zero out tasks; found in V1 |
| A17 | Graph tools are not worth relying on | One ablation slot wasted, or a missed gain |
| A18 | ±2-task noise on ~58 tasks | Wrong conclusions from single runs |
| A12 | Dec 2 main final deadline (Nov 12 paper is confirmed) | Miss the main deadline; verify on Kaggle |

## Open risks

- **Paper in 5 days (V1–V3).** Nothing is scored yet and Kaggle GPU quota is unknown. The paper may have to report a small, honest ablation. Earliest check: V1.
- **Paper entry is separate.** The owner must join the paper-track competition and accept its rules; only a *submitted* Writeup counts. Earliest check: today.
- **Novelty is scored.** A pure prompt-tuning report would score low; the graph-tools ablation is the novelty angle, and it may come out negative (still reportable).
- **31B startup or throughput** may fail (a reported 600 s server health guard). Earliest check: V1.
- **Small public set** makes gains hard to prove; relies on replicates and the held-out repo.
- **One daily leaderboard submission** (secondary source) limits how often we can check the real score.
