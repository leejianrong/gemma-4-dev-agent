# T3 and T9: edit failures and the small-model proxy (2026-11-13)

Aggregates only (rules 4b). Sources: the five console logs under `data/runs/` read with `analysis/small_model_log.py`, and the
four 31B traces read with `analysis/trace_questions.py`. Counts from logs are approximate (the log wraps lines and shows only
the first 100 characters of each thought).

## T3. Why edits are refused

**What cannot be answered.** The plan was to ask whether a whitespace-tolerant match would have found the refused `old_string`.
That needs the attempted string. The pod console logs do not contain it, and the pod runs saved only `job.log` (no
`raw/traces`). So for E4B and E2B this check is **not possible yet**. The 20% drop rule in tasks.md stays undecided.
Fix for the next pod job (T4): save the raw traces, the way the Kaggle runs do.

**What the logs do show.** The first 100 characters of the thought that follows each refused edit (a thought was shown for
almost all of them):

| Run | Refusals with a shown thought | Mention exact / whitespace / placeholder wording |
|---|---|---|
| E4B baseline | 38 | 15 (exact 5, whitespace 9, placeholder 3) |
| E4B v2 | 38 | 18 (exact 7, whitespace 14) |
| E2B baseline | 51 | 23 (exact 22, whitespace 5) |
| E2B v2 | 61 | 35 (exact 32, whitespace 1, placeholder 1, re-read 2) |

The models mostly say they must copy the text exactly, and E4B often names whitespace or indentation. Placeholder (`...`) wording is rare.
A first pass of this count was wrong (it matched the log's own trailing `...` and counted placeholders in nearly every thought);
this table uses word patterns only. The excerpt is short, so these are lower bounds.

**31B (traces, which keep arguments).** 22 of 474 `edit_file` calls were refused (4.6%): 18 text not found, 3 several matches, 1 no change.
(23 more errors were "call budget exhausted", which are not edit failures; see trace-findings Q2.) Multi-line `old_string` is
refused more often: 15 of 22 refused (68%) against 189 of 429 accepted (44%). n = 22.

**Reading.** The small models fail at exact reproduction of text they have already read, which is the mechanism the format papers
describe (papers.md). The cited remedies split: line-anchored edits showed about zero gain over `str_replace` for weak models in the
primary text, and the independent check found none (papers.md). So the v3 line-number prompt is a reasonable test, not a sure win. Judge it by
the refusal rate in the log (E4B baseline 41 of 106 edit calls, E2B 83 of 118), not by resolution.

## T9. Is E4B a fair proxy for 31B?

Signals both models report in the same log format. The 31B row is the one pod run (a3, L40S); the Kaggle 31B logs have no event
lines, so for the refusal rate the Kaggle traces give 22 of 474.

| Signal | 31B | E4B base | E2B base |
|---|---|---|---|
| Resolved of 36 | 13 to 15 | 5 | 6 |
| Median tool calls (limit 28) | 27.5 | 10.5 | 11 |
| Ran a test | 25% (pod run); 17 to 22% earlier | 83% | 39% |
| Edit refusals per `edit_file` call | 5% (Kaggle traces); 12% (pod: 11 of 89) | 39% | 70% |
| Tasks that never called `submit_patch` | 6% (pod run) | 11% | 19% |
| Time-outs | 4 (pod), 1 to 4 (Kaggle) | 0 | 5 to 6 |
| Mean thought per step, characters | 778 | 1,397 | 2,603 |

**Verdict: E4B is a proxy for E4B only.** It differs from 31B on every shared signal: it stops at about a third of the call
budget, tests far more often, and fails on edit mechanics that 31B mostly handles. A prompt change that raises E4B's score may be fixing
a problem 31B does not have, and a 31B-specific lever (first edit by call 7, trace-findings Q3) cannot be seen on a model that finishes in 10 calls.
Use E4B/E2B runs for questions about small-model failures and for the small-model bonus entry itself, not as a stand-in for 31B prompt tests.
Anything meant for the 31B final needs a 31B run (Kaggle quota, or a pod with 31B; see GPU_RUNS).
