# ADR-0003: 31B is the main entry; E4B/E2B is the second final submission

- Status: Accepted
- Date: 2026-11-07
- Deciders: owner

## Context
One base model per submission. Two final submissions are selected. The $10k small-model bonus
requires E2B or E4B and that the entry be one of the two finals. All public top bundles use 31B.

## Decision
Final submission 1 is the best 31B zip; final submission 2 is the best E4B or E2B zip. 31B must
first prove it starts and fits 12h (slice V1); if it cannot, fall back to 12B for the main entry.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Two 31B finals | Forgoes the bonus for little diversity |
| Small model only | Likely a much lower main-track score |
| 12B main | Only if 31B fails V1 |

## Consequences
Effort splits across two models, so the small entry gets less tuning. Ablation data on E4B/E2B
doubles as paper material. Models cannot be mixed within a submission.
