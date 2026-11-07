# ADR-0005: Reproduce the public budget-aware baseline, and judge changes by replicates

- Status: Accepted
- Date: 2026-11-07
- Deciders: owner

## Context
The best reproducible public bundle (flexonafft budget-aware v2, Apache-2.0, credits
matterhorn3838) scores ~0.17–0.18. The public leaderboard has ~58 tasks, so one task is ~1.7
points and identical zips reportedly vary by ~2 tasks. The hidden test set comes from private
repos, so overfitting to the public repos is a real risk. Other notebooks have no licence field.

## Decision
- Start from the flexonafft bundle with its attribution kept; do not copy other notebooks.
- Identify every experiment by the zip's SHA-256 and record it in `experiments/runs.csv`.
- Change one thing per variant. Replicate each variant at least twice.
- Hold out one public repo; accept a change only if it gains ≥3 tasks there and does not lose
  elsewhere. The public set is fastapi 67, rich 48, requests 13 and httpx 1 tasks, so the held-out
  repo is **rich** (httpx has one task and requests 13, too few to detect a 3-task gain).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Write our own prompt from scratch | Loses the one known-good reference point |
| Judge by one leaderboard submission | Within noise; one submission per day |

## Consequences
More runs per decision and a slower pace, in exchange for conclusions that survive noise. The
baseline's prompt bans graph tools on third-party evidence; we test that claim rather than trust it.
