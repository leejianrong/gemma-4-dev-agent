# Why the small models fail on the dev tasks

One replicate each of E4B and E2B on the 36 dev tasks, baseline prompt, one RTX 2000 Ada (GEM-35, A43).
E4B resolved 5 and E2B resolved 6; the 31B resolved 13 to 15 on Kaggle. This note reads the two console
logs to say what kind of failures these are and which a prompt can change. Aggregates only: the data
terms (rules 4b) forbid per-task ids, issue text, patches or transcripts in the repo.
Regenerate the tables with `python3 -I analysis/small_model_log.py E4B=<job.log> E2B=<job.log>
--gold data/map/gold_hunks.csv` (needs the local data).

## Outcomes

| | E4B | E2B |
|---|---|---|
| Resolved | 5 of 36 | 6 of 36 |
| Unresolved after a clean finish | 31 | 19 |
| Time-outs (8 minute limit) | 0 | 6 |
| Empty patch | 0 | 4 |
| Other error (no tool call to submit) | 0 | 1 |
| Median tool calls (limit 28) | 10.5 | 11 |
| Tasks that ended without calling `submit_patch` | 4 (11%) | 7 (19%) |

E4B never runs out of time or calls: it stops early with a wrong fix. E2B loses 11 of 36 tasks to
time-outs, empty patches and a missing submit before the fix is even tested.

## Tool errors

The agent gets an error back when a tool call is refused. Counts over the whole run:

| Error | E4B | E2B |
|---|---|---|
| `edit_file`: `old_string not found` | 37 | 49 |
| `edit_file`: string occurs several times | 4 | 18 |
| `edit_file`: "No changes to apply" (old and new string identical) | 0 | 16 |
| Tool call missing mandatory arguments | 1 | 7 |
| Path does not exist | 1 | 9 |
| Line range with start after end | 2 | 0 |
| Other | 0 | 2 |
| Total | 45 | 101 |
| Tasks with at least one error | 12 of 36 | 24 of 36 |
| `edit_file` errors per `edit_file` call | 41 of 106 (39%) | 83 of 118 (70%) |

For comparison the 31B baseline had 5 edit errors in 84 `edit_file` calls (about 6%; 3 more were budget
refusals, TRACE_REVIEW). Both small models fail to place an edit far more often, E2B on seven calls in ten. The most common error is the
exact-match one: the model retypes the text it wants to replace and gets a character wrong (the tool's own
message warns about escaping). The identical-string error is E2B only: it sends an edit that changes nothing.

## Behaviour

| | E4B | E2B |
|---|---|---|
| Thought length, mean characters (median) | 1,400 (660) | 2,600 (1,040) |
| Thought characters per task: resolved / unresolved | 18,000 / 23,000 | 12,700 / 23,400 |
| Thought characters per task: time-outs | none | 88,000 to 129,000 |
| Ran a pytest command | 30 of 36 (83%) | 14 of 36 (39%) |
| Last test run failed, among unresolved tasks that ran one | 18 of 25 | 13 of 13 |
| Edited a gold file (any task / unresolved only) | 26 of 36 / 21 of 31 | 25 of 36 / 19 of 30 |
| Tasks that edited only docs or tests | 1 | 1 |

Reading these together:
- **Finding the file is not the problem.** Both models edit a gold file in about 70% of tasks, the same
  share as the 31B (A42: 66% to 74%).
- **E2B time-outs are runaway reasoning.** The six tasks that hit the limit wrote 88,000 to 129,000
  characters of thought each, seven to ten times the resolved tasks. The sampling config allows a 4,096
  token thinking budget, which clearly does not stop this.
- **E4B stops on a failing test.** In 18 of the 25 unresolved tasks where it ran a test, its last run
  failed (the count includes failures unrelated to its change, so it is an upper bound), and it still
  finished with 18 calls to spare. A hidden-test failure after a visible one is the usual pattern.
- E4B is the only one that runs tests, and testing does not separate its solved from unsolved tasks
  (5 of 30 with a test, 0 of 6 without; too few to say more).

## What a prompt can and cannot change

| Problem | Share | Prompt? |
|---|---|---|
| Failed edits (E2B 70%, E4B 39% of edit calls) | the largest error class in both | Yes: copy rule, retry recipe |
| Identical old and new string (E2B) | 16 calls | Yes: one rule |
| Missing arguments in a tool call (E2B) | 7 calls | Partly: say all three arguments every time |
| No `submit_patch` call | 11% and 19% of tasks | Yes: the call is a tool, not text |
| Runaway reasoning in time-outs (E2B) | 6 of 36 tasks | Partly: a cap in the prompt; a lower `thinking_budget` in `sampling.yaml` is the stronger lever (a config arm, not a prompt) |
| Wrong fix that passes the model's own check (E4B) | most of 31 unresolved | Mostly capability; the "do not submit on a failing test" and "re-check the issue's exact strings" rules only trim the tail |
| Empty patch (E2B) | 4 tasks | Follows from failed edits and time-outs |

## The v2 bundles

Each is a copy of its v1 with only `prompts/system.md` changed. Changes are numbered so single ones can
be ablated later.

**`e2b_v2`** (708 words, 33% shorter than the baseline's 1,052):
1. Cut the prompt by a third: merged the locate bullets, dropped repeated rules and the long edit-retry paragraph.
2. Edit copy rule: `old_string` is one to three lines copied character for character from `read_file`, never retyped, no added escapes.
3. `new_string` must differ from `old_string` and contain the change; give `filepath`, `old_string` and `new_string` every time.
4. After `old_string not found`: `sed -n 'A,Bp'` the 10 lines, copy a line from that output, retry once; for several matches add the line above or below; after two failures one Python heredoc.
5. Finish by calling the `submit_patch` tool; never write it, or a diff, in a message.
6. Reasoning cap: about 150 words per step, never paste whole files into thoughts.

**`e4b_v2`** (1,129 words, 6% longer than the baseline):
1. Same edit copy rule and retry recipe as E2B changes 2 to 4, in fewer words.
2. If a test touching your change still fails after one fix, do not submit as it is: change approach or undo the edit.
3. Compare `git diff` with the step 1 list; spare calls go to this check, not to stopping early (the model uses about 10 of 28).
4. Call the `submit_patch` tool, never write it in a message.

## What each change should show in a log

| Change | Signal | Baseline value (E2B / E4B) |
|---|---|---|
| Edit copy rule and retry recipe | `edit_file` errors per `edit_file` call | 70% / 39% |
| Identical-string rule | "No changes to apply" count | 16 / 0 |
| Submit tool rule | tasks without a `submit_patch` call | 7 / 4 of 36 |
| Reasoning cap | time-outs; thought characters per task | 6 time-outs; 88,000 to 129,000 |
| Shorter prompt (E2B) | median calls and empty patches | 11 and 4 |
| Failing-test rule (E4B) | unresolved tasks whose last test run failed | 18 of 25 |
| Spare-calls check (E4B) | median calls; resolved count | 10.5; 5 |

Resolution counts are noisy at this size (`docs/ABLATION_PLAN.md`: about 8 to 9 points detectable with
three replicates, more with one), so read these signals first; a change that moves its signal but not the score is still worth keeping if it costs nothing.

## Method and limits

- One replicate per model, same 36 tasks and seed; the 31B comparison is from a different GPU and server setup.
- The parser reads the console log. Its tool-call counts equal the harness's own `calls=` in 25 of 36 (E4B)
  and 28 of 36 (E2B) tasks once `submit_patch` is left out, and over-count by one to four otherwise.
  Rates built on call counts are therefore approximate.
- "Last test failed" looks for the words failed or error in the output after a pytest command, so it
  includes unrelated failures.
- Gold files come from `data/map/gold_hunks.csv`; only shares are reported.
