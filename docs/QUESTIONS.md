# Decision register

Mode: Fresh (only a starter notebook + pasted competition page). Status: FORK = needs user, ASSUMED = default taken, DEFERRED = later.

Facts: score = % of tasks whose patch passes hidden validation tests (SWE-Bench style). Submission = `submission.zip` (agent.yaml, prompts, sub_agents, skills, optional LoRA). One base model for all agents. Harness tools fixed. 12h total for all tasks. Final deadline 2026-12-02 (entry/merge 2026-11-25). Two final submissions selectable. Today 2026-11-07, so ~25 days.

| # | Category | Question | Status | Default / answer |
|---|---|---|---|---|
| F1 | Scope | Harness-only (prompts/skills/sub-agents/sampling) vs also training a LoRA | FORK | Harness-only first, LoRA as a stretch slice |
| F2 | Deps | Base model: 31B / 12B / E4B / E2B | FORK | 31B |
| F3 | Runtime | Training/eval compute and money cap | FORK | No training spend until baseline exists; cap set by user |
| F4 | Scope | Paper track (Nov 12) in or out | FORK | Out |
| F5 | Runtime | Where the model runs for dev eval: Kaggle L4x4 notebooks only (quota-limited, no internet) vs rented GPU (RunPod, 4x24GB class) for the `swegemma eval` CLI | FORK | Kaggle notebooks for scored-parity runs; RunPod only if quota runs out (ties to F3) |
| F6 | Scope | Success target: prize placement vs beat sample baseline | FORK | Beat sample baseline measurably, then iterate |
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
| A12 | Deadline | Page text says both "Nov 12" and "Dec 2" for final submission; treat Dec 2 as final, Nov 12 as paper deadline | ASSUMED | verify on Kaggle Rules tab |
| D1 | Scope | RL / rejection-sampling fine-tune pipeline | DEFERRED | after baseline + F1 |
| D2 | Scope | Small-model $10k bonus (E2B/E4B) | DEFERRED | decided by F2 |
| A13 | Generalisation | Hidden test (~120 tasks) comes from *private* repos; public set is fastapi/rich/requests/httpx only. So no repo-specific prompt tricks; hold out one repo when judging changes | ASSUMED | from dataset description |
| A14 | Budget | 12h / ~120 tasks is ~6 min per task if serial. Sample uses 1 min, 10 tool calls, 50 turns; I will set per-task limits in eval_config.yaml from measured throughput | ASSUMED | concurrency at scoring unknown; verify |
| A15 | Context | 32,768-token window, compaction at 14k tokens, read_file capped 150 lines/10k chars, command output 5k chars. Design for small reads and an analyzer sub-agent via agent_tool | ASSUMED | from HARNESS_README |
| A16 | Failure | Harness auto-recovers an unsubmitted diff, strips test/config files; repro scripts must live in /tmp; edits to tests are discarded | ASSUMED | from HARNESS_README |
| A17 | Dependency | Graph tools use precomputed data and are offline; test set has identical graph generation. Use them in the analyzer sub-agent, measure whether they help | ASSUMED | |
