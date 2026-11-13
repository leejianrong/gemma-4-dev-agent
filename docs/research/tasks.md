# Candidate tasks from the research

Ordered by value for cost. GPU column: none / pod (about 0.5 USD per small-model replicate, 1.8 USD left) / Kaggle (quota gone).
"Done when" is the test that tells us it worked. Cards go on pandan board 45 (GEM) once agreed.

| # | Task | Direction | GPU | Done when |
|---|---|---|---|---|
| T1 | Trace analyses Q1 to Q4 ([spec](trace-analyses.md)) | 2, 1, 3 | none | **Done 2026-11-13**: [trace-findings.md](trace-findings.md); reducers in `analysis/trace_questions.py`, tested |
| T2 | Check template-bug symptom in the small-model logs and the 31B message lengths | 2 | none | **Inconclusive**: traces hold no thinking; visible text never empties after call 1. A pod probe would settle it |
| T3 | Edit-failure taxonomy: fuzzy-match candidates (whitespace, indentation, trailing newline) | 1 | none | **Partly done**: the logs do not hold the attempted strings, so the match test is not possible; [edits-and-proxy.md](edits-and-proxy.md) has what thoughts and 31B traces show. Needs raw traces from the next pod job |
| T4 | One E4B v3 replicate (line-number edits) on a pod | 1 | pod, about 0.5 USD | Row in `runs.csv`; edit-refusal rate against 39% (E4B baseline) and v2; resolution only as a side note (noise 8 to 9 points) |
| T5 | Same for E2B v3 (only after T4 shows a log signal) | 1 | pod, about 0.5 USD | Same |
| T6 | Time policy simulation: replay "cap at N calls" over the 31B traces | 3 | none | **Done: drop it.** Resolved runs submit at median call 22; a cap at 20 cuts 37 of 56 |
| T7 | Read in full: SWE-Verifier, LLM-as-a-Verifier, hashline benchmark, More with Less | 3, 1 | none | **Done**: [papers.md](papers.md). Verifiers: no. Hashline: about zero gain for weak models. Remaining-budget reminders: the only cheap idea |
| T8 | Read the Kaggle Discussion and Code tabs (needs login) | 5 | none | List of public tricks tried by others, marked tried or untried by us |
| T9 | Proxy check: do E4B prompt changes move the same log signals as 31B? Compare signals available in both | 5 | none (uses T1) | **Done**: E4B differs from 31B on every shared signal; a proxy for E4B only ([edits-and-proxy.md](edits-and-proxy.md)) |
| T10 | LoRA feasibility note: trajectory counts we can get, where they may live (rules 4b), cost on a pod | 4 | none | **Done: no-go for now** ([lora-feasibility.md](lora-feasibility.md)); 56 resolved runs over 17 tasks, terms question open |
| T11 | Make synthetic tasks harder (multi-line, multi-node patches) | 4, 5 | none | **Done in part (A48)**: same-file multi-site, 6 lines at 3 sites and 10 at 5, all verified. Not reached: 22.5-line bin, cross-file sites |
| T13 | Prompt A/B that moves the first edit earlier (31B) | 3 | Kaggle or pod L40S | Log signal median first-edit call drops by 3 or more from the baseline 11 to 14; edit refusals and timeouts not worse; resolution a side note. Needs a within-task look first (trace-findings Q3 has n=5) |
| T12 | Kaggle runs when quota returns: 31B arm for whichever of T3, T6 survives | all | Kaggle | Two replicates plus a log signal |

## Suggested order

T1, T6, T7, T9, T10 are done, T2 inconclusive, T3 partly. T13 next (needs a GPU), T11 is done in part (A48). The remaining no-GPU task is T8, which needs your Kaggle login, then T7 in parallel as reading. T4 only after T3 says edit formats are still the
live problem. T8 needs the owner's login. T10 and T11 wait: nothing above supports training yet.

## Constraints that bind every task

- No per-task data in the repo or on hosted APIs (rules 4b). Aggregates and code only.
- Pods: only `rp-job*` that we created; report cost after each job; keep the env gate (`pod/env_check.py`).
- Judge by log signal as well as resolution (11-point detection floor).
