# Research notes (2026-11-13)

Written while Kaggle GPU quota was spent and about 1.8 USD of the 10 USD RunPod cap was left. Question: what can
we learn without a GPU, and how do other people get round GPU limits? Web search only; no paper was read in full
and several results are search snippets or aggregator pages. Check a number against the paper before citing it.

| File | What it holds |
|---|---|
| [literature.md](literature.md) | What the sources say, by direction, with links and how far to trust each |
| [tasks.md](tasks.md) | Candidate tasks from the directions, ordered, with cost, GPU need and success test |
| [trace-analyses.md](trace-analyses.md) | Spec for the zero-GPU trace analyses (task T1) |

## Where we stood when this was written

- 31B baseline: 13 and 15 of 36 dev tasks (A40); public leaderboard 0.18. Skill and run-a-test prompt: no effect (A40, A41).
- Small models, baseline prompt: E4B 5, E2B 6 of 36 (A43). v2 prompts: E4B 8, E2B 5, one replicate each (A46).
- Small models fail first at placing an edit: 39% (E4B) and 70% (E2B) of `edit_file` calls refused, against about 6% for 31B (A44).
- Gold patch size separates solved from never-solved tasks (A42): over 10 changed lines resolve 11% of task-runs, 10 or fewer 57%.
- `e4b_v3` and `e2b_v3` (edit once, then replace by line number) are merged and have no run row yet.
- Detectable gain with two replicates of 36 tasks: about 11 points. Anything smaller needs a log signal (CLAUDE.md).

## Directions in one line each

1. **Edit mechanics for small models.** Exact-text edits are the known weak spot; line-anchored edits are the cited fix. Mixed evidence.
2. **Gemma 4 chat template.** Reported loss of reasoning after the first tool call. Checkable in traces we already have.
3. **Selection, verification, time policy.** Best-of-N does not fit an 8-minute task; early termination and time reallocation might.
4. **Fine-tuning on our own traces.** Allowed (LoRA), but we have about 15 resolved traces and rule 4b limits where traces may go.
5. **Working round the GPU limit.** Small proxy model (already doing it), offline mining of existing traces (free), synthetic tasks (A45).
