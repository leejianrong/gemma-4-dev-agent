# Candidate tasks from the research

Ordered by value for cost. GPU column: none / pod (about 0.5 USD per small-model replicate, 1.8 USD left) / Kaggle (quota gone).
"Done when" is the test that tells us it worked. Cards go on pandan board 45 (GEM) once agreed.

| # | Task | Direction | GPU | Done when |
|---|---|---|---|---|
| T1 | Trace analyses Q1 to Q4 ([spec](trace-analyses.md)) | 2, 1, 3 | none | `trace-findings.md` with a verdict per question; reducers tested |
| T2 | Check template-bug symptom in the small-model logs and the 31B message lengths | 2 | none | Part of T1 Q1; if positive, a prompt hypothesis written down |
| T3 | Edit-failure taxonomy: fuzzy-match candidates (whitespace, indentation, trailing newline) | 1 | none | Share of refused `old_string`s that a normalised match would have found, from logs. If under 20%, drop the idea |
| T4 | One E4B v3 replicate (line-number edits) on a pod | 1 | pod, about 0.5 USD | Row in `runs.csv`; edit-refusal rate against 39% (E4B baseline) and v2; resolution only as a side note (noise 8 to 9 points) |
| T5 | Same for E2B v3 (only after T4 shows a log signal) | 1 | pod, about 0.5 USD | Same |
| T6 | Time policy simulation: replay "cap at N calls" over the 31B traces | 3 | none | Estimated solved-task loss and seconds freed per N, from T1 Q3. Decide whether a prompt rule is worth a Kaggle run |
| T7 | Read in full: SWE-Verifier, LLM-as-a-Verifier, hashline benchmark, More with Less | 3, 1 | none | One page per source: setup, model size, whether it applies to 8 min and 28 calls |
| T8 | Read the Kaggle Discussion and Code tabs (needs login) | 5 | none | List of public tricks tried by others, marked tried or untried by us |
| T9 | Proxy check: do E4B prompt changes move the same log signals as 31B? Compare signals available in both | 5 | none (uses T1) | Table of shared signals; decide whether E4B is a fair proxy for 31B edit behaviour |
| T10 | LoRA feasibility note: trajectory counts we can get, where they may live (rules 4b), cost on a pod | 4 | none | Go or no-go paragraph in an ADR. Likely no-go: about 15 resolved traces |
| T11 | Make synthetic tasks harder (multi-line, multi-node patches) | 4, 5 | none | Mutants with gold patches median 10+ lines that still verify (A45 method) |
| T12 | Kaggle runs when quota returns: 31B arm for whichever of T3, T6 survives | all | Kaggle | Two replicates plus a log signal |

## Suggested order

T1 (with T2, T3, T6 falling out of it) first, then T7 in parallel as reading. T4 only after T3 says edit formats are still the
live problem. T8 needs the owner's login. T10 and T11 wait: nothing above supports training yet.

## Constraints that bind every task

- No per-task data in the repo or on hosted APIs (rules 4b). Aggregates and code only.
- Pods: only `rp-job*` that we created; report cost after each job; keep the env gate (`pod/env_check.py`).
- Judge by log signal as well as resolution (11-point detection floor).
