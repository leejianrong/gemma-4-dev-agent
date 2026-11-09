# Where does a code graph help a bug-fixing agent? Localization, co-change and noise on 129 graph-annotated Python tasks

*Subtitle: BM25 beats graph and embedding search at finding the edit site, call-graph neighbours predict the sibling edits, and a 58-task leaderboard cannot resolve a 3-task gain.*

Square-bracket source tags refer to rows in `docs/QUESTIONS.md` (A-numbers), run IDs in `experiments/runs.csv`, or figures in `figures/eda/`. Every number below has a tag.

## Abstract

We study code-graph retrieval on 129 public Gemma 4 Developer Agent tasks from four Python libraries. Each task includes a call graph and 256-d node embeddings. We map patches to nodes with old-file line numbers: 442 map to nodes, 164 are module-level, 26 are in new files, and 21 hit async functions [A24]. We measure retrieval without a language model. BM25 finds a gold node in its top 10 on 55% of 116 mapped tasks. Adding graph neighbours gives 54%; adding embedding neighbours gives 50% [A28]. After one edit, one-hop call neighbours find 23% of the remaining gold nodes at 23% precision, about 39 times chance. The same module contains 62% [A29]. The graph omits all `async def` nodes (0 of 239) [A27]. BM25 recall@10 changes little when we count async targets as unreachable: 43% on sync functions versus 41% with async targets included [A35]. We describe leaderboard noise and a Kaggle harness runner [A33, A34]. The first end-to-end baseline resolved 3 of 30 tasks [baseline30-2026-11-08].

## 1. Introduction

Bug-fixing agents spend most of their budget finding the relevant code in unfamiliar repositories. Graph and embedding tools are widely assumed to help. Some agents use repository graphs, call-graph queries, or learned embeddings. The Gemma 4 Developer Agent competition provides three graph and embedding tools alongside six file and shell tools. It gives agents a 32k-token context and a fixed 12-hour budget for about 120 hidden tasks [docs/COMPETITION.md]. The public data lets us compare retrieval methods: given an issue, which method finds a node edited by the real fix? We also ask what the graph adds after the first edit site is known.

We make six contributions:

1. We map gold patches to graph nodes exactly for 129 tasks and report validation counts [A24].
2. We compare BM25, graph expansion, embedding expansion, and random retrieval, including results by target kind [A28, A35].
3. We use a leave-one-out co-change analysis to test which structural relations predict other edited nodes [A29].
4. We measure the missing async nodes in the released graph and estimate their effect [A27, A35].
5. We model noise in small-n agent leaderboards [dashboards/noise.py].
6. We give a runner for the official Kaggle harness and describe the trace schema we observed [A33, A34].

## 2. Data

The public set contains 129 tasks: fastapi 67, rich 48, requests 13, and httpx 1 [A23]. The 127 graphs contain 367,985 nodes and 452k edges, all labelled `calls`. Each node has an ID, a name, and source text, but no line numbers [A23, A25]. Many nodes are outside the library code. In fastapi, about 9% belong to the package and about two thirds are tests. The library shares are 39% for requests, 55% for rich, and 56% for httpx [A26]. We score library nodes and report the all-node pool separately. Issues have a median length of 58 words. None includes a traceback or hint text [A25].

**Embeddings.** A node's vector depends on its text. Some 22% of nodes share a vector with another node; 99.5% of those groups have identical text. Raw cosine scores separate nodes poorly: random pairs average 0.79, and 97% of nodes have a neighbour scoring at least 0.99. After we subtract the mean vector, random pairs average 0.04. Just 5 of 256 components then carry 90% of the variance. We use these mean-centred vectors throughout [A26; figure eda_03].

## 3. Mapping patches to nodes

We use the base commit and the *old* file for each patch hunk. We walk its `ast` line ranges and assign each changed line to the innermost function or class. We checked the mapping in three ways. All 632 library hunks match the old file at the computed lines. All 318 function nodes contain their removed lines in the graph text. All 470 mapped nodes have a graph header that names them [A24].

We map 442 hunks to a node. Another 164 are module-level, 26 are in new files, and 21 hit async functions. At least one node maps for 116 of 129 tasks; 52 tasks have two or more mapped nodes [A24]. An earlier text-matching method gave a subset of this mapping for only 353 of 430 hunks, so we replaced it [A24].

## 4. Localization

We rank library nodes with BM25 over the issue text. For each of the 116 mapped tasks, hit@k means that at least one gold node appears in the top k. We compare BM25 with two expansion methods, a score-boost method, and random ranking. Graph expansion adds the 1-hop neighbours of the top 3 BM25 hits after the top 5. Embedding expansion does the same with mean-centred embedding neighbours. The boost method adds neighbour links to the score.

| Method | hit@10 (library pool) |
|---|---|
| BM25 | 55% |
| BM25, then graph | 54% |
| BM25, then embedding | 50% |
| Random | 0% |

BM25 recall at 1, 5, and 10 is 0.11, 0.36, and 0.42. Its hit@10 is 0.51 for fastapi, 0.53 for rich, and 0.82 for requests. When we include tests and docs, BM25 hit@10 falls to 35%. The boost method also does worse at small k: recall@1 is 0.05 versus 0.11 for BM25 [A28; figure eda_04]. We did not tune the settings (3 seeds, head 5, lambda 0.5). Thus BM25 ≥ graph > embedding describes these defaults, not a bound.

**By target kind.** We score 380 sync function nodes and 90 class nodes. Another 18 library hunks in 8 tasks fall in async functions [A35]. Graph expansion does not help on function targets (40% versus 43% for BM25). It helps on class targets (36% versus 25%, across 33 tasks). Expansion helps when the target is a class and the issue names its methods [A35; figure eda_07].

## 5. Co-change: what the graph does predict

Many patches edit more than one site. We take 50 tasks with 2 to 20 library gold nodes. For each task, we reveal one gold node and test which candidate sets contain the others. This is a leave-one-out analysis.

| Candidate set | size (nodes) | recall | precision |
|---|---|---|---|
| 1-hop call neighbours | about 5 | 23% | 23% |
| Same module | about 33 | 62% | 14% |
| 1-hop plus module | about 35 | 69% | 13% |
| 2-hop | about 35 | 56% | 12% |
| 10 embedding neighbours | 10 | 20% | 6% |

One-hop call neighbours beat chance by a median 39 times. Two hops increase the candidate set but lose precision. Embedding neighbours add little beyond the call graph [A29; figure eda_05]. After the first edit, an agent could check callers and other nodes in the same module. We have not tested that advice with a model; it is our first planned ablation.

## 6. The async hole

The released graph has no node for any async function in the files touched by gold patches: 0 of 239. It includes 4,646 of 4,646 sync functions in those files [A27]. FastAPI handles most requests asynchronously. Its async functions therefore cannot appear in results from the three graph tools, and 41 hunks fall back to a parent node. The graph also removes decorators and trailing comments. Class nodes contain only the header [A27]. The hidden set is built the same way, so the graph defect applies there too.

The measured localization cost is small. Only 18 library hunks in 8 tasks are async. Another 3 tasks edit only async code and cannot be scored. BM25 recall@10 is 43% on sync functions and 41% when async targets count as unreachable [A35].

## 7. Running the official harness on Kaggle, and what a score means

**Runner.** We run the competition's `Evaluator` in a CLI-pushed Kaggle kernel. It needs three undocumented settings: `machine_shape` set to `NvidiaL4`, the competition's Python 3.12 image, and the wheelhouse and model attached as inputs. Kaggle silently ignores `NvidiaL4x4` and supplies two T4s; vLLM then refuses bfloat16. Cold start takes 108 s for wheels and 385 s for the model [A33]. We observed the result and trace schema (ATIF v1.7) [A34] and normalise them in `docs/RUN_CONTRACT.md`.

**Baseline.** We use a reused budget-aware bundle with one agent, no adapter, 8 min, 28 tool calls, 80 turns per task, and the 31B w4a16 base [A31, docs/ATTRIBUTION.md]. Its prompt tells the agent never to use the three graph tools, so this baseline measures an agent that relies on grep and file reading, not one that uses the graph. On a stratified 30-task sample, it resolves 3 tasks (10%): fastapi 2 of 10, rich 1 of 10, requests 0 of 9, and httpx 0 of 1. Four tasks hit the session timeout, two hit the tool budget, and one returned an empty patch. The median task takes 5.2 minutes. The 30-task run takes 2.65 hours, which projects to about 10.6 hours for 120 tasks run one at a time [baseline30-2026-11-08]. A 5-task smoke run on the same zip resolves 0 [smoke-2026-11-08]. Of the 27 failures, 7 left no gradable patch (4 timeouts, 2 tool-budget stops, 1 empty patch). Of the 20 that did, 2 edited the wrong file, 4 broke the library with a syntax or import error, and 5 ran the tests and still failed an assertion. The other 9 could not be judged: the test run errored before any assertion ran, because of a missing test module or a broken fixture [analysis/failure_classes.py]. The same zip scores 0.18 on the public leaderboard (about 58 tasks, one submission, zip sha256 d66442e9), which is inside the noise band of our local 10% [baseline30-2026-11-08].

**Noise.** At a baseline near 17% on about 58 public-leaderboard tasks, one score has a 95% band of roughly plus or minus 9.7 points. We assume per-task variance of 0.05, which reproduces the roughly two-task noise others report. On the same tasks, about 6 replicates per variant detect a 5-point gain, and about 16 detect 3 points [dashboards/noise.py]. A single leaderboard comparison cannot settle a 3-task gain.

## 8. Related work

SWE-bench (Jimenez et al., 2024) studies repository-level issue resolution. This competition uses a similar task format with private repositories. SWE-agent (Yang et al., 2024) showed that the agent-computer interface affects resolution. Agentless (Xia et al., 2024) localizes in stages: file, function, then edit. It does so without an agent loop. As a strong, simple baseline, it fits our result that text retrieval is hard to beat. Graph-based localization includes RepoGraph (Ouyang et al., 2024), CodexGraph (Liu et al., 2024), and LocAgent (Chen et al., 2025). Compared with those systems, we test retrieval on gold nodes without a model and measure co-change. BM25 follows Robertson and Zaragoza (2009).

## 9. Limitations

- **Small public set.** Of 129 tasks, 116 have a mapped node. Two of the four repos have 13 or fewer tasks; httpx has 1. Most per-repo and per-kind results use n under 50, so their error bands are large.
- **Noise.** At this size, agent scores cannot separate gains of one to three tasks (Section 7). The 3/30 baseline has a wide interval. We do not claim it differs from 17%.
- **No model in the loop for Sections 4 to 6.** An agent also uses grep, `read_file`, and its own judgement. Our retrieval measures do not capture that behaviour.
- **Untuned.** We did not tune BM25 or expansion settings. Tuning might improve the graph methods.
- **Mapping.** Our mapping uses exact old-file lines but omits module-level hunks (164) and new files (26).
- **Hidden set.** Private repos may differ from these four. We hold out one repo (rich) when judging agent changes.

## 10. Reproducibility

Code: `github.com/leejianrong/gemma-4-dev-agent` (Apache-2.0). The analyses run as free Kaggle CPU kernels on the attached competition data (`pod/gold_map.py`, `pod/localize.py`, `pod/cochange.py`). Run `make eda` to regenerate the figures and `make run-eval` to run the harness. The submission bundle has a hash (sha256 d66442e9…). Every row in `experiments/runs.csv` records that hash. We do not release per-task annotations, traces or patches, because the competition data terms forbid redistributing the data. We release aggregates, figures and code that regenerates them.

## References

- Jimenez et al. SWE-bench: Can language models resolve real-world GitHub issues? ICLR 2024. arXiv:2310.06770.
- Yang et al. SWE-agent: Agent-computer interfaces enable automated software engineering. NeurIPS 2024. arXiv:2405.15793.
- Xia et al. Agentless: Demystifying LLM-based software engineering agents. 2024. arXiv:2407.01489.
- Ouyang et al. RepoGraph: Enhancing AI software engineering with repository-level code graph. arXiv:2410.14684.
- Liu et al. CodexGraph: Bridging large language models and code repositories via code graph databases. NAACL 2025. arXiv:2408.03910.
- Chen et al. LocAgent: Graph-guided LLM agents for code localization. ACL 2025. arXiv:2503.09089.
- Robertson and Zaragoza. The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in Information Retrieval, 2009.
