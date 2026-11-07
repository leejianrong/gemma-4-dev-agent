# ADR-0002: Harness first; no training until the baseline reproduces

- Status: Accepted
- Date: 2026-11-07
- Deciders: owner

## Context
Public bundles gain from prompt and budget changes alone (early scored runs of 0.05–0.08 to ~0.18). No one has
shown a LoRA gain. There are ~25 days left, no local GPU, and a $10 compute cap. The owner
wants LoRA, SFT, RL, distillation, quantization and pruning explored later.

## Decision
Milestones M1 and M2 change only the submission config (prompt, tools, sampling, limits). Any
training is deferred to slice V6 and only starts once a baseline run is in `runs.csv`.

## Alternatives considered

| Option | Why not |
|--------|---------|
| LoRA from day one | No baseline to compare against, no trajectories yet, and the $10 cap cannot fund a 31B run |
| Harness only, forever | Owner wants the advanced methods; they stay in scope as M3 |

## Consequences
Early results come fast and feed the paper. Training starts late, so it may produce only a
spike. Quantization and pruning can be studied but not shipped: only the four `w4a16-ct`
bases and `.safetensors` LoRA adapters are accepted.
