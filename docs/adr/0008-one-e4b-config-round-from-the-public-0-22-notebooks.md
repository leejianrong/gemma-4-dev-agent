# ADR-0008: One E4B config round from the public 0.22 notebooks (amends ADR-0007)

- Status: Accepted
- Date: 2026-11-23
- Deciders: owner (asked to carry it out)

## Context
ADR-0007 stopped E4B prompt and budget arms. Since then both LoRA variants regressed E4B (A65, A66), and the
two public notebooks at 0.22 on the main board (against our 0.18) showed a config-only change we never tested:
40 tool calls instead of 28, a one-word answer after `submit_patch` with an immediate submit when the call budget
is spent, and the full issue text pinned at the end of the system prompt (`{problem_description}`). They are 31B
notebooks; we cannot run 31B locally, so E4B is the proxy for the log signals.

## Decision
- Run exactly two arms on the 36 dev tasks, one replicate each, through pueue: `e4b_cfg3` (all three changes)
  and `e4b_cfg1` (40 calls only). Control is `e4b_v2` (5, 6 and 5 of 36 in three replicates).
- Judge by the log signals first (tool-budget runs, empty patches, first-edit call, calls per task), then
  resolution; a gap under about 11 points is not a result (A54).
- ADR-0007 otherwise stands: no further E4B arms, and the second final stays `e4b_v2` unless an arm shows a
  clear signal. The result goes to the 31B entry as a candidate (one daily submission, owner's call).

## Consequences
Costs about 3 hours of local GPU. If neither arm moves a signal, the 31B baseline stays as submitted.
