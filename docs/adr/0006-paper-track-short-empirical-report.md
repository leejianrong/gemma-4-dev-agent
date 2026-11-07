# ADR-0006: Enter the paper track with a short empirical ablation report

- Status: Accepted
- Date: 2026-11-07
- Deciders: owner

## Context
The owner wants a paper out as soon as possible. The deadline is 2026-11-12 23:59 UTC (confirmed from the paper-track page); today is 2026-11-07.
Nothing has been scored yet and Kaggle quota is unknown. The paper track is a separate Kaggle
competition: a Kaggle Writeup (max 3,000 words: title, subtitle, abstract, introduction,
methods and experiments, related work and citations), optional public notebook, scored 0-5 on
novelty, quality (generality), relevance, verifiability and clarity. Prizes: best paper $15k, best
new resource $10k, best new application $10k. Unsubmitted drafts are ignored, and any private
Kaggle resource attached becomes public after the deadline.

## Decision
Write a Kaggle Writeup centred on one testable question: do the provided code graphs and
embeddings help a small offline SWE agent, or is a budget-aware prompt enough? Method: a
controlled graph-tools on/off ablation with replicates (plus budget and model-size variants as
context) and a failure taxonomy. Release the labelled trajectories and the run table as a
resource, which is also what the best-new-resource prize looks for. Every number comes from
`runs.csv`. If data is thin by Nov 11, submit what exists and
say so in the limitations.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Skip the paper | Owner decided otherwise |
| Wait for LoRA/RL results | Cannot finish before the deadline |
| Large novel method paper | No time and no budget |
| Pure prompt-tuning report | Scores low on novelty and generality; the graph-tools question is on the listed topics |

## Consequences
V1 and V2 are scheduled so their data lands before Nov 11. Time spent writing competes with
tuning. The paper claims only what was measured, which may be modest. Verifiability and clarity
are the criteria we can win on, so the code, prompts, zip hashes and run table are public. Public
release of trajectories must be checked against the competition data terms before upload.
