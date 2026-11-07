# ADR-0006: Enter the paper track with a short empirical ablation report

- Status: Accepted
- Date: 2026-11-07
- Deciders: owner

## Context
The owner wants a paper out as soon as possible. The deadline is 2026-11-12 (a secondary source
says 13 Nov IST); today is 2026-11-07. Nothing has been scored yet, Kaggle quota is unknown, and
the rules and format have not been read. A $35k award exists for the best paper.

## Decision
Write a short report on what moves the score of a small offline SWE agent under a hard budget:
the baseline, one-change ablations (graph tools, budget, thinking, model size), and a failure
taxonomy. Every number comes from `runs.csv`. If data is thin by Nov 11, submit what exists and
say so in the limitations.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Skip the paper | Owner decided otherwise |
| Wait for LoRA/RL results | Cannot finish before the deadline |
| Large novel method paper | No time and no budget |

## Consequences
V1 and V2 are scheduled so their data lands before Nov 11. Time spent writing competes with
tuning. The paper claims only what was measured, which may be modest.
