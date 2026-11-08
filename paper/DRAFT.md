# Where does a code graph help a bug-fixing agent? Localization, co-change and noise on 129 graph-annotated Python tasks

*Subtitle: BM25 beats graph and embedding search at finding the edit site, call-graph neighbours predict the sibling edits, and a 58-task leaderboard cannot resolve a 3-task gain.*

Source tags in square brackets point to rows in `docs/QUESTIONS.md` (A-numbers), to `experiments/runs.csv` (run ids) or to figures in `figures/eda/`. Every number below has a tag.

## Abstract

Code-graph and embedding tools are widely assumed to help software-engineering agents find where to edit. We test that assumption on the public set of the Gemma 4 Developer Agent competition: 129 real bug-fix tasks from four Python libraries, each shipped with a call graph and 256-d node embeddings. We map every gold-patch hunk to a graph node exactly, using the old-file line numbers (442 hunks mapped, 164 module-level, 26 in new files, 21 in async functions) [A24]. Then we measure three things without a language model in the loop. First, plain BM25 on the issue text puts a gold node in its top 10 for 55% of 116 tasks; appending graph neighbours gives 54% and embedding neighbours 50% [A28]. Second, the call graph does carry signal about *other* edits: neighbours one hop from an edited node contain 23% of the remaining gold nodes at 23% precision, about 39 times chance, and the same module contains 62% [A29]. Third, the released graph has no node for any `async def` (0 of 239) [A27], yet this costs little for localization (BM25 recall@10 43% on sync functions against 41% with async counted as unreachable) [A35]. We also give a noise model for the competition's small leaderboard and an open pipeline for running the official harness from a Kaggle kernel [A33, A34]. A first end-to-end baseline run resolved 3 of 30 tasks [baseline30-2026-11-08].

## 1. Introduction

Agents that fix bugs in unfamiliar repositories spend most of their budget finding the right code. Recent systems add structure to help: repository graphs, call-graph queries and learned embeddings. The Gemma 4 Developer Agent competition ships exactly these as tools: three graph and embedding tools beside six file and shell tools, with a 32k-token context and a fixed 12-hour budget for about 120 hidden tasks [docs/COMPETITION.md]. Its public data lets us ask a narrow, answerable question: given the issue text, how often does each retrieval method name the node the real fix edited, and what does the graph add beyond text?

Contributions:

1. An exact mapping from gold patches to graph nodes for 129 tasks, with validation counts [A24].
2. A localization comparison (BM25, graph expansion, embedding expansion, random) with the target split by kind [A28, A35].
3. A leave-one-out co-change analysis showing which structural relations predict sibling edits [A29].
4. A measured defect in the released graph (no async nodes) and an estimate of what it costs [A27, A35].
5. A noise model for small-n agent leaderboards [dashboards/noise.py].
6. A recipe and runner for the official harness on Kaggle GPUs, with the trace schema as observed [A33, A34].

## 2. Data

The public set has 129 tasks: fastapi 67, rich 48, requests 13, httpx 1 [A23]. Graphs hold only `calls` edges (452k over 367,985 nodes in 127 graphs); nodes carry an id, name and source text but no line numbers [A23, A25]. Most nodes are not library code: in fastapi about 9% are the package itself and about two thirds are tests, while requests, rich and httpx are 39%, 55% and 56% library [A26]. We therefore score on library nodes only and report the all-node pool separately. Issues are short (median 58 words), none carries a traceback or hint text [A25].

**Embeddings.** The vector is a function of node text: 22% of nodes share a vector with another node and 99.5% of those groups have identical text. Raw cosine is nearly uninformative (random pairs average 0.79; 97% of nodes have a neighbour at 0.99 or higher). After mean-centring, random pairs average 0.04 and 5 of 256 components carry 90% of the variance. We use mean-centred vectors throughout [A26; figure eda_03].

## 3. Mapping patches to nodes

For each hunk we walk the *old* file's `ast` line ranges at the base commit and credit each changed line to the innermost def or class. Validation: 632 of 632 library hunks match the old file at the computed lines; 318 of 318 function nodes contain all their removed lines in the graph text; 470 of 470 mapped nodes have a graph header naming them [A24]. Results: 442 hunks map to a node, 164 are module-level, 26 are new files and 21 hit async functions. 116 of 129 tasks have at least one mapped node and 52 have two or more [A24]. The earlier text-matching method was a subset of this mapping for only 353 of 430 hunks, which is why we replaced it [A24].

## 4. Localization

We rank library nodes by BM25 over the issue text and measure whether a gold node is in the top k (hit@k) over the 116 mapped tasks. Methods: BM25; BM25 then the 1-hop graph neighbours of the top 3 hits appended after the top 5; the same with mean-centred embedding neighbours; a boost variant that adds neighbour links to the score; and random.

| Method | hit@10 (library pool) |
|---|---|
| BM25 | 55% |
| BM25, then graph | 54% |
| BM25, then embedding | 50% |
| Random | 0% |

BM25 recall at 1, 5, 10 is 0.11, 0.36, 0.42, and hit@10 is 0.51 for fastapi, 0.53 for rich and 0.82 for requests. Over all nodes (tests and docs included) BM25 hit@10 falls to 35%. The boost variant is worse at small k (recall@1 0.05 against 0.11) [A28; figure eda_04]. Parameters were not tuned (3 seeds, head 5, lambda 0.5), so the ordering BM25 ≥ graph > embedding is a finding about defaults, not a bound.

**By target kind.** The graph has 380 sync function nodes and 90 class nodes among the scored targets, plus 18 library hunks in 8 tasks that fall in async functions [A35]. Graph expansion does not help on function nodes (40% against 43%) but helps on class nodes (36% against 25%, 33 tasks). Expansion is useful when the target is a class and the issue names its methods [A35; figure eda_07].

## 5. Co-change: what the graph does predict

Localization finds one edit site; patches often touch several. We take 50 tasks with 2 to 20 library gold nodes, reveal one gold node and ask which candidate sets contain the others (leave-one-out).

| Candidate set | size (nodes) | recall | precision |
|---|---|---|---|
| 1-hop call neighbours | about 5 | 23% | 23% |
| Same module | about 33 | 62% | 14% |
| 1-hop plus module | about 35 | 69% | |
| 2-hop | | 57% | 12% |
| 10 embedding neighbours | 10 | 20% | 6% |

One-hop neighbours beat chance by a median 39 times. Two hops add size without precision, and embedding neighbours add little over the call graph [A29; figure eda_05]. The practical reading is a prompt-level one: after the first edit, check the edited function's callers and its module neighbours. We have not tested this with a model; it is the first planned ablation.

## 6. The async hole

In the files that gold patches touch, 0 of 239 async functions have a graph node, against 4,646 of 4,646 sync ones [A27]. FastAPI's request handling is mostly async, so the three graph tools cannot return those functions, and 41 hunks fall back to a parent node. The graph also strips decorators and trailing comments, and class nodes hold only the header [A27]. Because the hidden set is built the same way, this applies to it. Its effect on localization is small: only 18 library hunks in 8 tasks are async, and 3 more tasks edit only async code and cannot be scored. BM25 recall@10 is 43% on sync functions and 41% counting async targets as unreachable [A35]. We report the hole as a property of the benchmark and the cost as small.

## 7. Running the official harness on Kaggle, and what a score means

**Runner.** We run the competition's own `Evaluator` in a CLI-pushed kernel. Three undocumented settings were needed: `machine_shape` `NvidiaL4` (the spelling `NvidiaL4x4` is silently ignored and gives two T4s, where vLLM refuses bfloat16), the competition's Python 3.12 image, and the wheelhouse and model attached as inputs. Cold start is 108 s for wheels plus 385 s for the model [A33]. The result and trace schema (ATIF v1.7) are in [A34]; we normalise them into a documented contract (`docs/RUN_CONTRACT.md`).

**Baseline.** The agent is a reused budget-aware bundle with one agent, no adapter, 8 min, 28 tool calls and 80 turns per task, and the 31B w4a16 base [A31, docs/ATTRIBUTION.md]. On a stratified 30-task sample it resolved 3 (10%): fastapi 2 of 10, rich 1 of 10, requests 0 of 9, httpx 0 of 1. Four tasks hit the session timeout, two the tool budget and one returned an empty patch. The median task took 5.2 minutes, 2.65 hours for 30, or about 10.6 hours projected for 120 tasks run one at a time [baseline30-2026-11-08]. A 5-task smoke run on the same zip resolved 0 [smoke-2026-11-08]. Leaderboard result: PENDING (one submission, zip sha256 d66442e9).

**Noise.** With a baseline near 17% on about 58 public-leaderboard tasks, one score has a 95% band of roughly plus or minus 9.7 points. Assuming per-task variance of 0.05, which reproduces the roughly two-task noise others report, about 6 replicates per variant detect a 5-point gain on the same tasks and about 16 detect 3 points [dashboards/noise.py]. A single leaderboard comparison of two variants therefore says little about a 3-task gain.

## 8. Related work

SWE-bench (Jimenez et al., 2024) frames repository-level issue resolution; this competition uses a similar task format with private repositories. SWE-agent (Yang et al., 2024) showed the effect of the agent-computer interface on resolution. Agentless (Xia et al., 2024) localizes hierarchically (file, then function, then edit) without an agent loop and is a strong, simple baseline, which fits our finding that text retrieval is hard to beat. Graph-based localization includes RepoGraph (Ouyang et al., 2024), CodexGraph (Liu et al., 2024) and LocAgent (Chen et al., 2025); our contribution relative to them is a controlled, model-free comparison on gold nodes and the co-change result. BM25 follows Robertson and Zaragoza (2009). *(TODO before submit: verify each citation's venue and year.)*

## 9. Limitations

- **Small public set.** 129 tasks, 116 with a mapped node, and three of the four repos have 13 or fewer tasks (httpx has 1). Per-repo and per-kind numbers carry large error bands; most are from n under 50.
- **Noise.** Agent results at this size cannot separate gains of one to three tasks (Section 7). The 3/30 baseline has a wide interval and we do not claim it differs from 17%.
- **No model in the loop for Sections 4 to 6.** The agent also uses grep, `read_file` and its own judgement, which our retrieval numbers do not model.
- **Untuned.** BM25 and expansion parameters were not tuned; the graph methods might improve with tuning.
- **Mapping.** The node mapping is exact on the old file but ignores module-level hunks (164) and new files (26).
- **Hidden set.** Private repos may differ from these four. We hold out one repo (rich) when judging agent changes.

## 10. Reproducibility

Code: `github.com/leejianrong/gemma-4-dev-agent` (Apache-2.0). Analyses run as free Kaggle CPU kernels over the attached competition data (`pod/gold_map.py`, `pod/localize.py`, `pod/cochange.py`); figures regenerate with `make eda`; the harness runs with `make run-eval`. The submission bundle is hashed (sha256 d66442e9…) and every run row in `experiments/runs.csv` carries that hash. Derived annotations are not released until the dataset terms are checked (A-register, GEM-22).
