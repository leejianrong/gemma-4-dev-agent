# The Gemma 4 Developer Agent Competition: reference

The facts about the competition in one place, for developers and agents who were not in the
conversations that produced this repo. Read this before changing the submission, the evaluation
setup, or the plan.

**Provenance.** Written 2026-11-07 from (a) the competition pages (Overview, Description,
Evaluation, Timeline, Prizes, Dataset Description) and the paper-track pages as pasted by the repo
owner, and (b) Kaggle's `HARNESS_README.md`. Both were paraphrased, not copied. Sections say where a
claim is **measured by us** or **unverified**. Kaggle can change the rules: the Rules tab and
`HARNESS_README.md` win over this file. Fetch the harness guide with
`kaggle competitions download gemma-4-developer-agent -f HARNESS_README.md`. We keep it in the
gitignored `data/` directory.

- Competition: https://www.kaggle.com/competitions/gemma-4-developer-agent
- Related repo docs: [`PLAN.md`](PLAN.md), [`SLICES.md`](SLICES.md), [`QUESTIONS.md`](QUESTIONS.md),
  [`adr/`](adr/). Board: Pandan board `GEM` ("Gemma 4 Developer Agent").

## 1. In one paragraph

Build the **configuration** of an autonomous coding agent (system prompts, sub-agents, skills,
sampling settings, optional LoRA adapters) that Kaggle compiles into a Google ADK agent running on a
quantized **Gemma 4** model, **offline**, on 4×L4 GPUs. Given a Python repository frozen at the commit
before a real bug fix, plus the issue text, the agent edits files in a sandbox and submits a patch.
Kaggle applies the patch in a fresh container, adds the hidden tests, and runs pytest. **Score =
share of tasks whose required tests all pass.** The whole run is limited to **12 hours**.

## 2. Problem statement

The organizers' framing: the best coding agents today rely on large cloud models; small local models
have improved but still struggle with multi-turn software engineering on large codebases. The
competition asks participants to **post-train or configure an open model into a reliable agent that
navigates complex codebases and drafts fixes for real software issues, on everyday hardware**,
using fine-tuning and reinforcement-learning ideas, better prompts and tools, and the provided code
graphs and embeddings.

What is and is not allowed to vary:

| You can change | You cannot change |
|---|---|
| System prompt, sub-agents (`agent_tool`), workflow agents (Sequential, Parallel, Loop) | The set of tools: only the 9 built-ins exist (section 6) |
| Sampling and thinking settings, per-task limits in `eval_config.yaml` | The base model family and the four allowed variants |
| Skills: `SKILL.md`, resource files, and Python or bash scripts run in the task sandbox | The sandbox, context compaction, the 32,768-token window |
| LoRA adapters, different ones per agent | The code graphs and embeddings (precomputed, identical for the hidden set) |

Tasks are **real-world Python bug fixes and feature requests** graded with pytest.

## 3. How a submission is scored

1. **Phase 1 (agent).** In a sandbox (container A) holding the repo at `base_commit`, the agent works
   with the tools until it calls `submit_patch`, runs out of budget, or is nudged three times without
   progress. Any unsubmitted working-tree diff is recovered automatically.
2. **Phase 2 (verification).** A fresh container B applies the agent's patch (four fallback passes),
   resets any test or test-runner files the patch touched, applies the hidden `test_patch`, and runs
   pytest on the target tests.
3. A task is **resolved only if** pytest exits 0 **and** the JUnit report shows every required test
   (fail-to-pass, pass-to-pass, or functions from `test_patch`) passing with no failures, errors or
   skips. Resolved = 1, otherwise 0. If the patch cannot be applied the task fails.
4. **Score** = resolved tasks ÷ tasks in the split, in [0, 1].

Edits to test files and runner configuration (`test_*.py`, `*_test.py`, anything under `tests/`,
`conftest.py`, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`, `sitecustomize.py`, `*.pth`
and similar) are **stripped and discarded**. The agent must fix library code.

**Time.** The agent has **12 hours in total** for all tasks, including sandbox setup but excluding
patch validation. Per-task limits are optional in `eval_config.yaml`. The per-task clock starts only
after container setup finishes.

**Leaderboard.** The public leaderboard scores a subset of the test set. Per the dataset page the
hidden test set has about 120 tasks, split evenly between a public and a private part, curated from
private repositories, and filtered so that a larger frontier model passes or comes within one test.
Third-party notebooks report a public leaderboard of about 58 tasks, so one task is about 1.7 points
and identical zips are reported to differ by about two tasks (unverified, third party).

## 4. What you submit

A zip named `submission.zip` with `agent.yaml` at the archive root:

```
submission.zip
├── agent.yaml            required root config (Google ADK Agent Config, restricted)
├── eval_config.yaml      optional per-task limits
├── configs/sampling.yaml optional, loaded with !include
├── prompts/*.md          optional, loaded with !include
├── sub_agents/*.yaml     optional sub-agents or AgentTool configs
├── adapters/<name>/      optional PEFT LoRA: adapter_config.json + adapter_model.safetensors
└── skills/<name>/        optional ADK skill: SKILL.md (+ scripts/, resources/)
```

Rules (from the harness guide):

- Declarative only: no Python entry point. Everything is YAML resolved against closed registries.
  `!include` paths are relative to the including file; no absolute paths, `..`, or symlinks.
- **Exactly one base model** across every agent and sub-agent, one of the four in section 5.
- Total unpacked size **under 3 GiB** including adapters. Allowed extensions only: `.yaml`, `.yml`,
  `.md`, `.txt`, `.py` (skill scripts), `.json`, `.safetensors`.
- Generation config: `max_output_tokens` 1 to 32,768 (default 16,384); `thinking_budget` 0 to 32,768
  (default 4,096; positive enables thinking, 0 disables it). With vLLM, omit `thinking_level` and use
  `include_thoughts: true` plus a `thinking_budget`. Fields that bypass the sandbox (`tools`,
  `system_instruction`, `http_options`, `safety_settings`, `response_schema`) are rejected.
- Agent types: `LlmAgent` (default), `SequentialAgent`, `ParallelAgent`, `LoopAgent` (1 to 500
  iterations). The session state provides `{problem_description}` and `{hints}` for templating.
- Up to **two final submissions** can be selected for judging (stated in the bonus-prize rules).
  Teams of up to five (secondary source).

## 5. Models, LoRA and hardware

| Model | Notes |
|---|---|
| `gemma-4-31b-it-qat-w4a16-ct` | Starter-kit default, highest ceiling, about 16 to 18 GB of weights |
| `gemma-4-12b-it-qat-w4a16-ct` | vLLM needs an `--hf-overrides` architecture override (applied by the harness) |
| `gemma-4-e4b-it-qat-w4a16-ct` | Small-model bonus eligible |
| `gemma-4-e2b-it-qat-w4a16-ct` | Small-model bonus eligible |

- **Scoring hardware:** 4 × NVIDIA L4 (24 GB each, 96 GB total), vLLM with tensor parallel 4,
  `gpu_memory_utilization` 0.90, `max_model_len` 32,768, gemma4 tool and reasoning parsers. No
  internet. Kaggle's L4x4 notebooks consume GPU quota at twice the usual rate and are only available
  for notebooks attached to this competition, with internet disabled.
- **LoRA:** `.safetensors` PEFT adapters only, rank up to 128 (the server right-sizes `max_lora_rank`
  from what it finds). Different agents may use different adapters (`adapter: name` on an agent).
  Rough sizes at rank 16 on 31B: 110 to 220 MB per adapter; rank 128: 0.9 to 1.8 GB.
- Quantizing or pruning the base model is **not submittable**: only the four `w4a16-ct` bases and
  adapter weights are accepted.

## 6. The agent's tools and the sandbox

The nine built-in tools (the only ones the agent can call, apart from sub-agents via `agent_tool`):

| Tool | Counts toward the tool-call budget | Notes |
|---|---|---|
| `run_command(command)` | yes | `/bin/bash -c` in `/workspace`; stdout and stderr each capped at 5,000 chars; 300 s default timeout |
| `read_file(filepath, start_line, end_line)` | yes | at most 150 lines and 10,000 chars per call |
| `edit_file(filepath, old_string, new_string, allow_multiple)` | yes | exact, then whitespace-flexible, then regex matching; fails if not unique |
| `write_file(filepath, content)` | yes | creates parent directories |
| `submit_patch()` | **no** | `git add -N .` then `git diff`; ends the task once the turn finishes |
| `get_status()` | **no** | live budget and patch status |
| `get_code_neighbors(node, edge_type, max_neighbors)` | yes | callers and callees from the precomputed graph |
| `search_similar_code(query, k)` | yes | cosine similarity over precomputed embeddings; takes a symbol name, not free text |
| `get_code_subgraph(nodes)` | yes | induced subgraph for a list of symbols |

Sandbox: Python 3.13 image, **no network**, 4 GiB RAM, 2 vCPUs per container. Dependencies are
preinstalled; `pip install` fails. Skill scripts run in the same persistent container, share its
filesystem, and their time counts against the budget. Scratch files created inside `/workspace` end
up in the patch, so use `/tmp`. The harness writes `pytest.ini` and `conftest.py` into the baseline
commit; editing them shows up in the diff and is discarded at verification.

Defaults and limits (`eval_config.yaml` can change the per-task ones):

| Limit | Harness default | Starter sample |
|---|---|---|
| Per-task wall clock | 60 min | 1 min |
| Tool calls | 100 | 10 |
| Turns | 500 | 50 |
| Command timeout | 300 s | 300 s |
| Verification pytest timeout | 300 s (fixed) | |

Context management: events compaction every 15 events at a 14,336-token threshold (retaining 5
events), context caching, and up to 5 retries with backoff on transient model errors. If a turn ends
without `submit_patch` the harness nudges the agent, resetting after any valid tool call and
stopping after three consecutive empty turns. A response cut off by the token limit gets a targeted
nudge to emit a smaller tool call.

## 7. The dataset

Training/public files ship in the competition download (about **20.9 GiB**; the Kaggle notebook
mounts them at `/kaggle/input/competitions/gemma-4-developer-agent/`):

| File | What it is |
|---|---|
| `tasks.jsonl` | 129 public tasks: `instance_id`, `repo`, `base_commit`, `problem_statement`, `hints_text`, `patch` (gold fix), `test_patch` (hidden-test equivalent), `created_at`. The hidden set omits `patch` and `test_patch`. |
| `snapshots/` | 129 `.tgz` repo snapshots frozen at `base_commit`, with future history removed (20.02 GiB, about 155 MB each) |
| `graphs/` | 127 NetworkX JSON graphs (plus 129 task-named hard links): nodes with `id`, `name`, `text`; edges with `source`, `target`, `type`, `key` |
| `embeddings/` | 127 `.npz` files (plus task-named links): one float32 vector of length 256 per graph node |
| `wheels/`, `docker/`, `sandbox/setup.py` | offline Python wheels and sandbox build files |
| `sample_submission/` | a runnable baseline ADK submission |
| `HARNESS_README.md` | the harness reference |

`submission.parquet` (`id`, `prediction`) is what the scoring run writes: the unified diff, or
`NO_PATCH`.

**Measured by us** (CPU kernels on the public data, 2026-11-07):

- Repos: fastapi 67 tasks, rich 48, requests 13, httpx 1. The hidden set comes from other,
  private repositories, so avoid repo-specific tricks.
- Graphs contain only `calls` edges (452,588 in total). Nodes carry **no line numbers**.
- Embeddings cover every graph node. Every public task has a graph and embeddings.
- `hints_text` is empty for all 129 public tasks.
- Mapping a gold patch to graph nodes by text matching is about 70% precise (hand-checked); a
  line-number-based mapping is planned (`QUESTIONS.md` A24).

How the tasks were built (dataset page): mined commits that change both library code and tests;
matched each to its issue; dropped mechanical refactors, docs-only and ambiguous changes; verified
that the tests fail without the fix and the full suite passes with it; for the hidden set also
checked that a frontier model solves or nearly solves each case.

## 8. Timeline

All deadlines are 11:59 PM UTC.

| Date | Event |
|---|---|
| 2026-09-22 | Paper track opens |
| 2026-09-23 | Main competition opens |
| **2026-11-12** | **Paper track final submission** (a Kaggle Writeup) |
| 2026-11-25 | Entry deadline (rules must be accepted) and team-merger deadline |
| **2026-12-02** | **Main competition final submission** |

## 9. Prizes

| Prize | Amount |
|---|---|
| Main track 1st / 2nd / 3rd | $37,000 / $18,000 / $10,000 |
| Small-model bonus (best entry using E2B or E4B, must be one of the two selected finals) | $10,000 |
| Paper track: overall best paper | $15,000 |
| Paper track: best new resource (dataset, library, software) | $10,000 |
| Paper track: best new application | $10,000 |

Top entries are to be highlighted at a Google-hosted expo (for example at NeurIPS 2026).

## 10. The paper track

A separate Kaggle competition. You submit a **Kaggle Writeup** of at most **3,000 words** of
original, unpublished research: title, subtitle, abstract, introduction, description of methods and
experiments, related work with citations. Optionally attach a **public notebook** (a private Kaggle
notebook attached to a public writeup becomes public after the deadline, as does any private
resource) or upload an arXiv-ready PDF as a public project link. You must join the paper-track
competition; **only a submitted writeup counts**, a saved draft is ignored. Participation in the
main competition is not required.

Each paper is scored 0 to 5 on five equally weighted criteria, and the final score is the average:
**novelty** (new insight or properties of existing methods), **quality** (how general the approach is
beyond the competition), **relevance** (impact on software engineering and agentic learning),
**verifiability** (enough detail to understand how an innovation works and how data was obtained,
analysed and interpreted), and **clarity**. Suggested topics: parameter-efficient fine-tuning and
RL for SWE agents; code-graph generation, parsing and embedding; new tasks, benchmarks and datasets
for code structure; reasoning over large graphs. Using the released graph and embedding data is
encouraged but not required.

## 11. Unverified or conflicting points

Check these on Kaggle before relying on them:

- **Which date is the main final deadline.** The main page's prize text says submissions are due
  Nov 12, but its timeline lists Dec 2. Nov 12 looks copied from the paper track; we assume Dec 2.
- **Winner licence.** A secondary source says winners must license their submission under Apache-2.0;
  another Gemma hackathon used CC-BY 4.0. The repo is Apache-2.0 (ADR-0001); verify on the Rules tab.
- **Only 31B allowed?** The same secondary source says every agent must use 31B. The official page
  lists four models, which is what we follow.
- **One leaderboard submission per day, five paper submissions** (secondary source).
- **Whether derived data may be released.** Needed before publishing any benchmark annotations or
  trajectories; the dataset terms have not been read.
- **Scoring-time concurrency** for tasks is unknown, so "about 6 minutes per task" (12 h ÷ ~120
  tasks, if serial) is a floor, not a plan.
- **Third-party scores** (about 0.17 to 0.18 for budget-aware bundles, claims up to 0.24) come from
  public notebooks and are self-reported.
- **The starter sample's own leaderboard score** is not known to us.

## 12. Where things are in this repo

| Need | Look at |
|---|---|
| Local submission pre-flight (mirrors the limits above) | `scripts/submission.py`, `make check`, `make zip` |
| The current placeholder agent | `submission/` |
| Free Kaggle CPU analyses of the data | `pod/explore.py`, `pod/audit.py`, `pod/eda_extract.py`, `make kernel` |
| Cost-safe GPU pod job template and rehearsal | `pod/job.sh`, `pod/rehearse/`, `make rehearse` |
| Decisions and their reasons | `docs/adr/`, `docs/QUESTIONS.md` |
