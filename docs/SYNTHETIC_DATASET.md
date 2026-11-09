# Synthetic task set (design, GEM-83)

Status: design only, nothing built. Written 2026-11-09.

## Why

A real run costs 2.65 h per 30 tasks, and detecting a 5-point gain needs about 6 replicates of 58
tasks (`dashboards/noise.py`). That is too slow for the many questions we want to ask: prompt
ablations, sampling and thinking sweeps, limits, sub-agents and workflow agents. A synthetic set in
the competition's format would give cheap runs, exact ground truth, repos we can hold out, and a
dataset we may publish (see "Release").

It is a **screening tool**. It is only useful if it ranks variants the way the real set does, so the
validity check below decides whether we use it at all.

## Repos

We do not reuse fastapi, rich, requests or httpx. The real set already covers them, and the
competition's tasks come from specific commits of those repos, which could count as Competition
Data (rules 4b, see `docs/COMPETITION.md` section 11). Licences below are from each package's PyPI
metadata, read 2026-11-09. All are permissive.

| Group (style it mimics) | Repos (licence) |
|---|---|
| Web and HTTP (fastapi, httpx) | starlette (BSD-3), werkzeug (BSD-3), flask (BSD-3), httpcore (BSD-3), h11 (MIT) |
| CLI, text and rendering (rich) | click (BSD-3), typer (MIT), pygments (BSD-2), markdown-it-py (MIT), mistune (BSD-3), jinja2 (BSD-3) |
| Small libraries (requests) | attrs (MIT), arrow (Apache-2.0), tenacity (Apache-2.0), cachetools (MIT), sqlparse (BSD-3) |
| Reserve | toolz (BSD-3), more-itertools (MIT), sortedcontainers (Apache-2.0), boltons (BSD-3), humanize (MIT), pyyaml (MIT), tomli (MIT) |

Left out: pydantic (large Rust core, heavy build), tqdm (MPL-2.0, file-level copyleft; avoidable).

**Selection rule from GEM-16.** 9 of 27 baseline failures were inconclusive because the test run
errored (missing `dirty_equals`, `inline_snapshot`, a broken `httpbin` fixture). So a repo is
admitted only if its tests run offline in the competition's image with pytest and what is already
installed. We pin each repo to one commit SHA and check this before generating anything.

**Manifest, fetcher and readiness check (GEM-87).** `synthetic/repos.json` pins all 23 repos (the
16 main and 7 reserve) to the latest release tag and its full commit SHA, with the licence read from
the LICENSE file at that SHA, the module names, the package dir and the tests dir.
`python -m synthetic.fetch CACHE` clones each at its tag and refuses any checkout whose HEAD is not the
pinned SHA. `python -m synthetic.readiness CACHE` parses each repo's tests with `ast` (no repo code
runs) and rejects a repo that imports a module outside stdlib, pytest, its own package and its
declared runtime dependencies, uses a plugin fixture or marker, a network fixture, or needs Python
above 3.13. Imports under `try/except ImportError` and files pytest does not collect are ignored.
Result on 2026-11-09: 9 admitted (click, typer, markdown-it-py, mistune, cachetools, sqlparse,
more-itertools, sortedcontainers, tomli) and 14 rejected, all licences permissive. What we could not
determine: the competition image's installed packages (the list is per repo and unpublished), so a
declared runtime dependency is assumed to be present and any test-only dependency counts as
missing. Some rejections are cautious: flask builds modules at test time, and toolz imports
`annotationlib`, which exists only in Python 3.14.

## Bug injection

1. **Mutate.** Parse each library file with `ast` and apply one operator at a time: swap a
   comparison or boolean operator, change an off-by-one constant, drop a guard `if`, swap two
   arguments, return a wrong value, change a default argument, remove a call. We keep the operator
   list short and log which one made each task.
2. **Gold node.** Take the innermost function or class that contains the mutated line, using the
   same old-file line mapping as `pod/gold_map.py` (A24). This gives the exact gold node with no
   text matching.
3. **Multi-site tasks.** Real tasks often edit several nodes (52 of 116 mapped tasks have two or
   more). For a share of tasks we apply 2 to 3 mutations in nodes that are call-graph or
   same-module neighbours, so the co-change findings (A29) can be tested.
4. **Async.** Keep async functions as targets. A switch drops them from the graph, as the released
   graph does (A27), so we can test that hole on purpose.
5. **Gold patch.** The inverse of the mutation is the gold patch; the mutated tree is the base.

## Tests that fail before and pass after

The existing test suite is the source. For each mutant:
- Run coverage once per repo to map test to functions, so only covering tests are run per mutant.
- Keep a mutant only if 1 to 5 tests fail on the mutated tree and all pass on the original. Those
  are the fail-to-pass tests; the rest of the covering tests are pass-to-pass.
- Discard mutants no test catches (equivalent or untested) and mutants that fail more than 5 tests
  (too broad to resemble a real issue).
- Run each kept task in the competition's sandbox image three times: twice on the mutated tree
  (the same tests must fail both times) and once with the gold patch applied (all must pass). This
  rules out flaky tests.

## Issue text

Real issues are short (median 58 words), have no tracebacks, no hints, and name an edited symbol
in 23 of 129 cases (A25). The generator must match that.
- **Writer.** Gemma 4 E4B on Kaggle, given the failing test's name and assertion message and the
  *behaviour* the mutation breaks, but **not** the diff or the function's name. A template is the
  fallback for a control arm.
- **Prompt rules.** User-style report, 30 to 100 words, no traceback, no code from the patch.
- **Leak checks** (reject and regenerate on failure): no line of the gold patch appears verbatim;
  the gold node's name appears in about 20% of issues, to match the real 18% (we set this rate on
  purpose, not by accident); no diff-style tokens.
- **Calibration check.** BM25 hit@10 on the synthetic set should land near the real 55% (we accept
  45% to 65%), and median issue length near 58 words. If BM25 is far above 55%, the issues leak or
  the bugs are too local, and we change the writer before running any agent.

## Graph and embeddings

Format, from A23, A25 and `docs/COMPETITION.md`: one graph JSON per repo with nodes
`{id, name, text}` (dotted ID such as `pkg.module.Class.method`, source text, no line numbers)
and edges all of type `calls`; one `.npz` per repo with a float32 vector of length 256 for every
node.
- **Graph builder.** Our own `ast` walk with best-effort static call resolution. The competition's
  builder is unknown, so we run ours on the real repos and compare aggregate numbers (node counts,
  edge counts, share of library nodes, degree distribution) with the real graphs. We do not publish
  per-node comparisons (rules 4b).
- **Embeddings.** The competition's model is unknown, so we use our own code-embedding model and
  project to 256-d with a fixed random projection. Identical text gives an identical vector, as in
  the real data (22% of nodes share a vector). Real layout (A36): the `.npz` holds one array per
  node, named by the node's dotted ID, each `float32` of shape `[256]`.
- **Task file.** `tasks.jsonl` has one JSON object per line with the fields `instance_id`, `repo`,
  `base_commit`, `patch`, `test_patch`, `problem_statement`, `hints_text`, `created_at`, all strings
  (A36). The harness must accept the bundle without changes.

## Stages

| Stage | Contents | Output | Go/no-go gate |
|---|---|---|---|
| 1. Localization only | Mutations, gold nodes, issue text, graphs, embeddings. No tests. | About 600 tasks (16 repos, about 40 each) | BM25 hit@10 within 45 to 65%; name-leak rate about 20%; builder aggregates close to the real graphs |
| 2. Runnable | Add fail-to-pass and pass-to-pass tests, sandbox checks | About 200 tasks, with a 60-task dev subset | Gold patch passes and mutant fails in the sandbox, twice, for every task |
| 3. Validity | Run variants on both sets (next section) | Rank agreement table | Pass rule below |

Stage 1 is enough to evaluate skill-script localizers at scale (GEM-80, GEM-81) and needs no GPU
beyond the issue writer.

## Stage 2a result (2026-11-10)

`synthetic/run_tests.py` runs a repo's tests in Docker (image `docker/synthetic`, built once with
network by `make synthetic-image`; every run uses `--network none`, a read-only root, the repo
mounted read-only and copied to a tmpfs scratch dir where the mutated file is dropped in, no
capabilities, a non-root user, 1 GB, 2 CPUs, 256 pids and a wall-clock timeout). Per repo it runs the
unmutated suite 3 times (tests failing in any run are excluded from every mutant's kill set), then
for each mutant the test files that name the module, then the full suite, then a rerun of the
killing tests. A mutant is **usable** when 1 to 5 tests fail only on it; those are its fail-to-pass
set. Reproduce: `python -m synthetic.fetch CACHE NAME...`, then
`python -m synthetic.run_tests CACHE NAME... --n 40`.

40 mutants per repo (20 for more-itertools, whose suite takes 43 s), drawn with seed 0 from files
under the package directory:

| Repo | Tests | Baseline pass | Flaky | Suite s | Mutants | Usable | Too broad | No test fails | Timeout | Kill rate | Usable share | s per mutant | Usable per 500 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| click | 2434 | 98.9% | 0 | 7.4 | 40 | 7 | 22 | 11 | 0 | 72% | 18% | 5.6 | 88 |
| typer | 1469 | 72.4% | 0 | 12.7 | rejected |  |  |  |  |  |  |  |  |
| markdown-it-py | 981 | 91.8% | 0 | 2.0 | 40 | 6 | 12 | 10 | 12 | 45% | 15% | 38.7 | 75 |
| mistune | 1324 | 100.0% | 0 | 7.4 | 40 | 9 | 14 | 13 | 4 | 57% | 22% | 41.7 | 112 |
| cachetools | 416 | 100.0% | 0 | 1.5 | 40 | 13 | 22 | 0 | 5 | 88% | 32% | 29.8 | 162 |
| sqlparse | 537 | 100.0% | 0 | 3.0 | 40 | 10 | 27 | 3 | 0 | 92% | 25% | 3.2 | 125 |
| more-itertools | 765 | 100.0% | 0 | 43.4 | 20 | 15 | 2 | 0 | 3 | 85% | 75% | 88.1 | 375 |
| sortedcontainers | 300 | 100.0% | 0 | 4.8 | 40 | 21 | 13 | 4 | 2 | 85% | 52% | 12.3 | 262 |
| tomli | 17 | 100.0% | 0 | 1.0 | 40 | 32 | 5 | 3 | 0 | 92% | 80% | 2.9 | 400 |

*Kill rate* is the share of mutants that make at least one test fail (not "no test fails", not a
timeout). Mutant runs time out at 8 times the suite time, capped at 120 s. The first five repos in
the table ran with 3 workers in parallel and no cap, so their seconds per mutant are inflated by
timeouts.

- **Totals.** Of 300 mutants, 113 are usable (38%), 117 are too broad (more than 5 tests fail), 44
  are caught by no test and 26 time out (loops from a dropped guard or a shifted constant).
- **Flaky.** None: no test changed outcome across the 3 unmutated runs of any admitted repo, and no
  usable mutant failed its rerun.
- **Baselines.** click has 27 and markdown-it-py about 80 tests that fail unmutated offline; they are
  excluded. typer is **rejected**: its pass rate is 72.4%, because its tutorial tests run example
  scripts through `coverage`, which the image does not have (with `coverage` installed the suite
  exceeds 120 s). The other 8 repos pass the 90% rule.
- **Yield.** At 500 mutants per repo the 8 admitted repos give about 1,600 usable tasks (sum of the
  last column), well above the 600 planned for stage 1. The cost is the main limit: the weighted mean
  is about 24 s per mutant, so 4,000 mutants take about 26 h on one worker or about 7 h on four.
  Lowering the timeout cap to 30 s would likely cut most of the cost in markdown-it-py, mistune and
  cachetools.
- **Open.** The "too broad" share (39%) is high because core functions are used by many tests.
  Raising the limit from 5 to 10, or choosing the most specific tests, would recover some of them;
  that is a stage 2b choice. The competition sandbox may lack packages the image has (its list is
  not published), so a usable mutant here is not proof that the same suite runs there.

## Validity check (does the proxy rank like the real set?)

1. Choose at least 6 variants that differ in ways we care about: baseline, thinking budget 0 vs
   4,096, a stricter locate-then-edit prompt, a tighter tool budget, the BM25 skill, a graph-tools-on
   prompt. Four variants are too few to say anything about rank correlation.
2. Run every variant on the real dev subset and on the synthetic dev subset, with enough replicates
   that `dashboards/noise.py` says a 5-point difference is detectable on the real set (about 6).
3. Report (a) Spearman rank correlation of mean scores, (b) the share of variant pairs whose
   difference exceeds the noise band on one set and has the same sign on the other, and (c) the
   scatter of effect sizes.
4. **Pass rule (proposed):** at least 80% sign agreement on pairs that exceed the noise band, and
   rank correlation of at least 0.7. Below that we use the synthetic set only for localization and
   cost questions, not for agent ranking. A failed check is still a result for the paper: it says
   where synthetic tasks stop being a good stand-in.
5. Keep one repo out of every synthetic experiment, as we do with rich on the real set.

## Size and cost (estimates, not measured)

- **Stage 1:** CPU only. Graph and embedding builds take minutes per repo. Issue writing is about
  600 to 3,000 short generations (under 1M tokens), under an hour on one L4. Cost: Kaggle quota,
  no RunPod spend.
- **Stage 2:** mutation runs are roughly 16 repos x 500 mutants x a few seconds, so single-digit CPU
  hours, split over free Kaggle CPU kernels.
- **Agent runs:** assume 2 to 3 minutes per synthetic task, since edits are small, against 5.3
  minutes on the real set. One replicate of a 60-task dev subset would then take about 2 to 3 h.
  This is an assumption until the first run. Any RunPod use is reported against the $10 cap.
- **Our time:** about 2 days for stage 1, 3 more for stage 2, after the paper deadline.

## Where we would use it

- **Prompt ablations** (GEM-29 to GEM-32): screen many prompts cheaply, then confirm the top few on
  the real dev subset.
- **Sampling, thinking and limit sweeps** (GEM-14, GEM-15): temperature, `thinking_budget`,
  `max_output_tokens`, per-task limits. These need many replicates, which is where cheap runs help.
- **Sub-agents and workflow agents**: planner then editor, parallel candidates, a Loop until tests
  pass. These cost more model calls per task, so a fast proxy matters most here.
- **Skill-script localization** (GEM-80, GEM-81): offline scoring at scale in stage 1.
- **Hold-one-out tests** across many repos, which four real repos cannot give.

## Release

Synthetic tasks are derived from public repos and our own mutations, not from the competition's
data, so the 4b restriction does not apply. We still must:
- Keep each repo's copyright and licence text; Apache-2.0 repos (arrow, tenacity, sortedcontainers)
  also need their NOTICE files, and the release says the files are modified.
- Ship a manifest with the repo, commit SHA and licence for every task.
- Include no competition files, no real-graph comparisons per node, and nothing generated from the
  competition's task text.
- Check the Gemma terms of use for outputs before publishing generated issue text.
- Publish the generator code under Apache-2.0 with the dataset, so others can regenerate it.

## Risks

- **Easier, more local bugs than real issues.** Absolute scores will not transfer. The validity
  check tests ranking only.
- **Issue text that is too clean.** Handled by the leak checks and the BM25 calibration.
- **Test environment gaps.** Handled by admitting a repo only after its suite runs in the sandbox.
- **Our own graph differs from the real one.** Matters for graph-tool studies, not for text search.
