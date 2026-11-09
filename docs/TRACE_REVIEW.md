# Baseline trace review (GEM-66)

What the 30 baseline traces (run `baseline30-2026-11-08`, 3 resolved, 27 not) show about how the
agent spends its budget. Aggregates only: the competition rules forbid publishing per-task data
(terms 4b), so there are no task ids, issue text, patches or quoted code here.
Reproduce: `python -m analysis.trace_review RUN_DIR [GOLD_HUNKS_CSV]`. The second argument also splits
the results by failure class (`analysis/failure_classes.py`).

**How to read the numbers.** There are 3 solved tasks, so any solved-versus-failed comparison is a
hint, not a result. "Calls" are tool calls in the raw trace: 755 over 30 tasks (run_command 373,
read_file 250, edit_file 84, submit_patch 35, write_file 11, get_status 2). Time per call is the
gap between agent-step events, so it includes the model's generation time for that call. I looked at the
full sequence of tool calls, statuses and sizes of all 30 traces and computed the aggregates over all
of them. I did not read the model's message text step by step, so the review says what the agent did,
not why.

## 1. Behaviour patterns

| Pattern | Count |
|---|---|
| Calls before the first edit (median) | 15 of the 28-call budget (54%); medians 6 searches and 5 reads, the rest scripts and version-control commands (15%) |
| Seconds before the first edit (median) | 139 s of a 281 s median task (the limit is 480 s) |
| Share of shell commands that are searches (grep, find, ls) | 56% (210 of 373); they take 27% of all step time (2,237 of 8,259 s) |
| Ad hoc reproduction scripts (shell commands that run Python or write a script) | 115 commands (31% of shell commands), about 3.8 per task |
| Tasks with 4 or more reproduction scripts in a row | 8 of 30: 6 of the 20 unsolved with a patch, 2 of the 3 budget stops, 0 of the 3 solved |
| Calls to the project's own tests (pytest) | 5 commands in 30 tasks; 17% of tasks ran any tests |
| Tasks that ran a test or a script after their last edit | 60% (18 of 30) |
| Tasks that read a test file | 13% (4 of 30) |
| read_file calls on the same file again | median 6.5 repeats per task over a median 2 distinct files (the 150-line read window forces paging) |
| Graph tool calls | 0 of 755 (the baseline prompt bans them) |
| Tasks with more than 28 calls in the raw trace | 13 of 30; 47 calls past the 28th; 7 were refused with a budget error (4 shell commands, 3 edits) |
| edit_file calls that failed | 8 of 84 (5 edit errors, 3 budget refusals) |
| Text-only turns (no tool call) | 50 of 805 agent steps (6%), 260 s in total (3% of step time) |
| Steps that took over 60 s | 21 of 805 (2.6%) but 25% of all step time; median 3,178 generated tokens |
| Generation speed | about 2.9 s per 100 generated tokens, so a 3,000-token step takes about 90 s |
| Prompt size | median 4.1k tokens at the first call, 9.8k at the last, 14.7k at most (the window is 32k) |
| Patches that add a new file (scratch script left in the patch) | 2 of 24 patches (8%); none touch test files |
| Used get_status to check the budget | 2 calls in 30 tasks |

By outcome class (medians; classes are small, so treat as descriptive):

| Class | Tasks | Calls | Before first edit | Edited | Verified after last edit |
|---|---|---|---|---|---|
| Resolved | 3 | 24 | 8 | 3 of 3 | 2 of 3 |
| Wrong fix (right file, test still fails) | 5 | 28 | 7 | 5 of 5 | 5 of 5 |
| Wrong file | 2 | 27 | 19 | 2 of 2 | 1 of 2 |
| Broke the library (syntax or import error) | 4 | 27.5 | 17.5 | 4 of 4 | 2 of 4 |
| Inconclusive test run | 9 | 26 | 14 | 9 of 9 | 7 of 9 |
| No patch, budget used up | 2 | 30 | 25 | 2 of 2 | 1 of 2 |
| No patch, empty | 1 | 36 | 8 | 1 of 1 | 0 of 1 |
| Timeout (8-minute limit) | 4 | 15.5 | 13 | 1 of 4 | 0 of 4 |

## 2. Solved versus failed

- **Solved tasks edited early.** Their median first edit came at call 8, against 15.5 for unsolved
  tasks with a patch. But the 5 wrong-fix tasks also edited early (call 7) and verified every time, so
  early editing is not enough: those agents edited quickly at the wrong place or with the wrong change.
- **Failure is mostly about where and what the agent edits, not whether it tries.** All 20 unsolved
  tasks with a patch edited, and 15 of the 20 ran something after their last edit. Of the 20, 2 edited
  the wrong file, 4 broke the library, 5 made a wrong fix, and 9 could not be judged (the test run
  errored; see `analysis/failure_classes.py`).
- **Reproduction loops show up in failures only.** The 8 tasks with 4 or more scripts in a row include
  6 unsolved tasks with a patch and both budget stops, and none of the 3 solved tasks (n=3, so a hint).
  The agent keeps re-running its own script instead of moving on to the edit or the real tests.
- **The two timeout and budget classes lose the whole task.** The 4 timeouts and 2 budget stops
  (20% of tasks) end without a graded patch; 3 of the 4 timeouts never edited. Each timeout burns the
  full 8 minutes: together they used about 32 minutes of the 159-minute run (20%).
- **Timeouts come from long generations, not slow tools.** The 4 timeout tasks hold 8 of the 21 steps
  over 60 s, and they made a median 15.5 calls in 8 minutes, against 26 across all 30 tasks.
- **One task looped on submit.** The one empty-patch task called `submit_patch` several times and
  alternated it with status commands, with no edit landing. A line that says what to do when the
  diff is empty would cover it.
- **Context is never the limit.** The largest prompt was 14.7k tokens of 32k. The constraints that bind
  are the call budget, the time limit and the read window.
- **Nobody used the graph.** With the tools banned, the agent searched with grep (56% of commands) and
  paged through files. The graph question for agents is therefore untested by this run (GEM-13).

## 3. Testable ideas, each tied to a pattern

**GEM-29, locate-then-edit schedule.** Pattern: 15 of 28 calls and 139 s go before the first edit.
Test: tell the agent to make its first edit by call 10 and to state its target file by call 6; measure
calls before the first edit, resolution and timeouts. Caution from section 2: a schedule alone may
raise the wrong-fix count, so pair it with the localizer and judge by resolution, not by speed.

**GEM-30, recovery from exact-match edit failures.** Pattern: 5 edit errors (the harness's FileEditError,
which I take to be a failed exact-match edit) in 84 edit calls (6%) across 30 tasks, too few to move the score by more than about 1 task. Test only as a cheap
prompt line (re-read the lines before retrying the edit). Lowest priority of the four.

**GEM-31, targeted test selection.** Pattern: 5 pytest commands against 115 ad hoc scripts (3.8 per
task, 31% of shell commands, 13.8 s each), including runs of 4 or more scripts in 8 tasks; only 17% of
tasks ran the project's tests, and 60% ran something after their last edit. Test: tell the agent to run the test file nearest the edited module
instead of writing a script; measure the number of reproduction scripts, calls saved and resolution.
Also tell it to put scratch files in `/tmp` (2 of 24 patches carried a scratch file).

**GEM-32, uncertainty before each call.** Pattern: tokens are time (2.9 s per 100 tokens), and 21 long
steps hold 25% of all time, 8 of them in the timeout tasks. Extra reasoning before each call therefore
costs about 3 s per 100 tokens. Test a hard cap instead (`max_output_tokens` 2,048 against the current
8,192, and `thinking_budget` 2,048 against 4,096, GEM-15) and look at timeouts and long steps first.
Only try the uncertainty prompt with a limit of 50 tokens.

**GEM-68, which code the graph tools cannot see.** Pattern: zero graph calls, so the async-function gap
(A27) cannot have mattered in this run. It matters only in the graph-on arm (GEM-13); put it there, and
make the localizer's coverage of async functions and classes the answer instead.

**Budget awareness (no card yet).** Pattern: 13 of 30 traces went past 28 calls, 7 calls were refused
with a budget error (3 of them edits), and `get_status` was called twice. Test a line that says to
call `get_status` at call 20 and to edit by call 24, and compare empty-patch and budget-stop counts.

## 4. What a localizer call could replace

The pre-edit calls of a median task are 6 searches and 5 reads, plus scripts and version-control commands.
One call to the skill (top 10 by BM25, with file and line, plus same-file siblings; A37) could replace
most of the 6 searches and aim the first `read_file` at the right window instead of paging a file from
its start.

Estimate (inferred, not measured): the top 10 holds a gold node for 56.9% of tasks. A hit replaces about
5 of the 6 searches (a saving of about 4 calls once the skill call is added); a miss costs one extra call.
That is 0.569 x 4 - 0.431 x 1, about **2 calls per task**, or about 7% of the 28-call budget, plus about
50 s of the 139 s before the first edit. The ceiling is the 27% of step time now spent on searches.
The saving shrinks if a skill call counts against the budget and grows if it also removes read paging
(6.5 repeat reads per task). Whether skill calls are counted, and what a skill can see in the sandbox,
is the open question of GEM-79.

## 5. Numbers the paper might use

- Median calls before the first edit: 15 of 28 (54%), over 30 tasks (the median of per-task counts of
  tool calls before the first edit_file or write_file).
- Share of shell commands that are searches: 56% (210 of 373).
- Tests: 5 pytest commands in 30 tasks; 17% of tasks ran any tests.
- Long steps: 21 of 805 agent steps (2.6%) took over 60 s and held 25% of step time.
- Graph tool calls: 0 of 755.
- Tasks with more than 28 calls in the raw trace: 13 of 30.
