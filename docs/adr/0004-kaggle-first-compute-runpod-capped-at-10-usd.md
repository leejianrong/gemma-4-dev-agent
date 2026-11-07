# ADR-0004: Evaluate on Kaggle first; RunPod only if quota runs out, capped at $10

- Status: Accepted
- Date: 2026-11-07
- Deciders: owner

## Context
The local box has no GPU and 7 GB RAM. Kaggle L4x4 is the real scoring environment (internet
off) but is quota-limited and counts at twice the rate of older GPUs. The owner set a $10 cap.

## Decision
All model-in-the-loop runs happen in a Kaggle kernel on L4x4. RunPod is used only when Kaggle
quota is exhausted or for the V6 training spike, with a dead-man's-switch teardown and a hard
total of $10.

## Alternatives considered

| Option | Why not |
|--------|---------|
| RunPod for everything | $10 buys only a few hours of a 4x24 GB pod; not the scoring environment |
| Local CPU runs | Cannot serve any Gemma 4 model |

## Consequences
Experiments are slow, queued by quota, and batched. Results are scoring-faithful. $10 rules out
any 31B training; V6 targets E2B/E4B. Spend must be logged.
