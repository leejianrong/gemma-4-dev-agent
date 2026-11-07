# Decision register

Mode: Fresh (only a starter notebook + pasted competition page). Status: FORK = needs user, ASSUMED = default taken, DEFERRED = later.

Facts: score = % of tasks whose patch passes hidden validation tests (SWE-Bench style). Submission = `submission.zip` (agent.yaml, prompts, sub_agents, skills, optional LoRA). One base model for all agents. Harness tools fixed. 12h total for all tasks. Final deadline 2026-12-02 (entry/merge 2026-11-25). Two final submissions selectable. Today 2026-11-07, so ~25 days.

| # | Category | Question | Status | Default / answer |
|---|---|---|---|---|
| F1 | Scope | Harness-only (prompts/skills/sub-agents/sampling) vs also training a LoRA | DECIDED | Harness only first; LoRA, SFT, RL, distillation, quantization, pruning later as M3 | ADR-0002 |
| F2 | Deps | Base model: 31B / 12B / E4B / E2B | DECIDED | 31B main; also pursue E4B/E2B for the bonus | ADR-0003 |
| F3 | Runtime | Training/eval compute and money cap | DECIDED | $10 RunPod cap | ADR-0004 |
| F4 | Scope | Paper track (Nov 12) in or out | DECIDED | Yes, enter the paper track, as soon as possible (Nov 12) | ADR-0006 |
| F5 | Runtime | Where the model runs for dev eval: Kaggle L4x4 notebooks only (quota-limited, no internet) vs rented GPU (RunPod, 4x24GB class) for the `swegemma eval` CLI | DECIDED | Kaggle first; RunPod only if quota runs out | ADR-0004 |
| F6 | Scope | Success target: prize placement vs beat sample baseline | DECIDED | Reproduce the ~0.17 baseline, then beat it by >=3 tasks on a held-out repo | ADR-0005 |
| A1 | User | Primary user = the Kaggle grader (agent consumes only its own config); human reader = me | ASSUMED | |
| A2 | Data model | Task = instance_id/repo/base_commit; identity by instance_id | ASSUMED | from notebook |
| A3 | Storage | Config as plain files in repo, git-diffable, zipped by script | ASSUMED | |
| A4 | Concurrency | One writer (me); runs keyed by config hash + model + task subset | ASSUMED | |
| A5 | Interfaces | `make zip`, `make validate`, `make eval SUBSET=n` wrapping adk_submission validate + Evaluator | ASSUMED | |
| A6 | Failure | Agent must always call submit_patch before budget ends, even if partial; empty patch = fail | ASSUMED | |
| A7 | Deps | google-adk, litellm, vLLM, swegemma, adk_submission: all supplied by Kaggle wheelhouse, offline, not swappable | ASSUMED | |
| A8 | Runtime | Local box has no GPU, 7 GB RAM, Docker 29, kaggle CLI authed: local = editing, zip validation, and checking reference `patch` passes in the docker sandbox. Model-in-the-loop runs happen on Kaggle/rented GPU | ASSUMED | checked with nvidia-smi/docker/free |
| A9 | Measure | Metric = resolution rate on the 129 public tasks via `swegemma eval` (stratified dev/holdout split by repo), plus median wall-clock per task against the 12h budget | ASSUMED | |
| A10 | Security | No secrets involved; zip must have no symlinks, allowed extensions only, <3 GiB | ASSUMED | |
| A11 | Versioning | Each submission tagged in git with score; keep best two as finals | ASSUMED | |
| A12 | Deadline | Main final deadline Dec 2; paper deadline Nov 12 23:59 UTC (confirmed by the paper page) | ASSUMED | main-track date from the pasted page, verify on Rules tab |
| D1 | Scope | RL / rejection-sampling fine-tune pipeline, distillation | DEFERRED | slice V6, after baseline (F1) |
| D2 | Scope | Small-model $10k bonus (E2B/E4B) | DEFERRED | now slice V5 (F2) |
| A13 | Generalisation | Hidden test (~120 tasks) comes from *private* repos; public set is fastapi/rich/requests/httpx only. So no repo-specific prompt tricks; hold out one repo when judging changes | ASSUMED | from dataset description |
| A14 | Budget | 12h / ~120 tasks is ~6 min per task if serial. Sample uses 1 min, 10 tool calls, 50 turns. Best public bundle uses 8 min, 28 tool calls, 240 s command timeout, 80 turns, and an explicit call-plan in the prompt (edit by call 12). Start from those numbers, then tune from measured throughput | ASSUMED | concurrency at scoring unknown; verify |
| A15 | Context | 32,768-token window, compaction at 14k tokens, read_file capped 150 lines/10k chars, command output 5k chars. Design for small reads and an analyzer sub-agent via agent_tool | ASSUMED | from HARNESS_README |
| A16 | Failure | Harness auto-recovers an unsubmitted diff, strips test/config files; repro scripts must live in /tmp; edits to tests are discarded | ASSUMED | from HARNESS_README |
| A17 | Dependency | Graph tools: the best public bundles (budget-aware v2, ~0.17-0.18 public LB) *prohibit* them in the prompt as "return nothing useful". Default: do not rely on them; run an A/B (graph on vs off) before building an analyzer sub-agent around them | ASSUMED | reverses my earlier default; evidence is third-party, verify |
| A18 | Measure | Public LB scores so far: one author's early runs 0.05-0.08 (the starter sample's own score is unknown), budget-aware bundles ~0.17-0.18, claimed top ~0.24. Public denominator is ~58 tasks, so one task = ~1.7 points and identical zips reportedly vary by ~2 tasks. Do not chase differences under ~3 tasks; use many local runs, not one LB shot | ASSUMED | third-party, from data/refs |
| A19 | Failure | Startup risk: a 4xL4 pilot failed a 600 s inference-server health guard before any task ran. Slice 1 must confirm a 31B submission starts and finishes within limits | ASSUMED | third-party report |
| A20 | Reuse | Baseline = flexonafft budget-aware bundle (Apache-2.0, credits matterhorn3838 SuperAgent). Reuse with attribution kept in the prompt; other notebooks have no licence field, so no code reuse | ASSUMED | licence per notebook B |
| D3 | Scope | Base-model quantization/pruning as shipped artifacts | DEFERRED | not allowed by the rules (only four w4a16-ct bases + safetensors adapters); study only |
| A21 | Paper | Paper rules read 2026-11-07: Kaggle Writeup, 3,000 words, sections as above, five criteria (novelty, quality/generality, relevance, verifiability, clarity), deadline Nov 12 23:59 UTC; separate competition entry required | DECIDED | ADR-0006, slice V3 |
| A22 | Compute | Kaggle notebooks have no Docker daemon; use the subprocess sandbox in kernels, Docker only locally | ASSUMED | confirm in V1 smoke run |

Note: the Status column for F1-F6 is DECIDED; answers are in the last column and the ADRs.

## Coverage

| Category | Covered by |
|---|---|
| Primary user and actors | A1, PLAN Users |
| Scope boundary | F1, F4, D1-D3, PLAN Scope |
| Data model and identity | A2, ADR-0005 (zip hash) |
| State and storage | A3, A11, S3 runs.csv |
| Concurrency and conflict | A4 |
| Interfaces and contracts | A5, A6 |
| Failure behaviour | A6, A16, A19 |
| External dependencies | A7, A17, A20, F2 |
| Runtime and deployment | A8, A22, F3, F5 |
| Measurable success | F6, A9, A18 |
| Security and secrets | A10, R6 |
| Versioning and migration | A11 (tag each submission with score) |
