# Gemma 4 Developer Agent (Kaggle)

Entry for https://www.kaggle.com/competitions/gemma-4-developer-agent. We build `submission/`
(YAML agent config, prompts, skills, optional LoRA) that Kaggle compiles into a Google ADK agent.
Score = % of ~120 hidden SWE-style tasks whose patch passes hidden pytest tests.
Dates: paper deadline 2026-11-12 has passed (draft `paper/DRAFT.md`); entry/merge 2026-11-25; final 2026-12-02.
Read `docs/COMPETITION.md` first (rules, limits, dataset). Planning state: `docs/QUESTIONS.md` (A-rows
tag every number), plan `docs/PLAN.md`, arms `docs/ABLATION_PLAN.md`, decisions `docs/adr/`, run log
`experiments/runs.csv`, GPU recipe `docs/GPU_RUNS.md`.

## Status: trust the code over the docs
- `submission/` is the adopted public baseline (flexonafft v2). Public leaderboard 0.18; 31B on our
  36 dev tasks resolves 13 and 15. Skill, run-a-test prompt: no effect (A40, A41). Small models: E4B 5,
  E2B 6 of 36 (A43). Active: prompt bundles in `experiments/bundles/`, small-model tuning (GEM-36).
- Board: pandan, GEM = board 45. `pandan comment add CARD --body "..."` needs `--body`; `pandan move`
  prints only a help line even when it works, so verify with `pandan get`.

## Commands
- `make` lists targets. `make setup` installs dev tools and the pre-push hook.
- `make check` = lint + unit tests + submission pre-flight. Same as pre-push and CI.
- `make score-local` scores the localizer on `data/competition` inside an isolated container.
- `make task-features` relates dev-task outcomes to task features (aggregates only).
- `make zip` builds `dist/submission.zip` (hash must match what `runs.csv` records).
- `make rehearse` is timing-sensitive: on a busy machine several heartbeat checks fail. Not a gate.

## Rules that are not obvious from the code
- **Competition data terms (rules 4b).** Never publish, commit or upload per-task data: gold nodes,
  hunks, traces, patches, issue text, failure classes by task id. Aggregates, figures and code that
  regenerates them are fine. Paper-track rules say the same. Hosted LLM APIs would receive task
  text: do not use them on real tasks.
- **Never run code from downloaded repos or tasks on the host.** Use the container pattern in the
  Makefile (`RUN_ISOLATED`: no network, read-only data, resource limits). Our scripts only parse
  snapshots with `ast`, in memory.
- Data lives in `data/` (gitignored). Fetch with `python scripts/fetch_data.py` (kaggle login, rules
  accepted). Kaggle answers HTTP 429 to a temporary token after about 260 files; the main login worked.
- google-adk, litellm, vllm, swegemma, adk_submission exist only on Kaggle; do not add them to pyproject.
- One base model for every agent. 32,768-token context. read_file: 150 lines / 10k chars.
- Hidden tests come from private repos. No repo-specific prompt tricks; hold out rich when judging a change.
- Resolution cannot detect gains under about 11 points with two replicates of 36 tasks: judge prompt
  changes by a log signal too (call of the first edit, edit failures, calls per task).
- No GPU here (7 GB RAM). Model runs happen on Kaggle L4x4 or a RunPod pod.

## GPU time
- Kaggle: weekly quota, L4x4 counts double (about 15 h, about five 36-task runs). The CLI cannot cancel
  a kernel (`kaggle kernels delete -y` cancels); a push over quota fails with "Maximum weekly GPU quota".
- RunPod: use the `runpod-jobs` skill and `pod/job.sh`, `pod/gpu_run.py`, `pod/pod_cmd.py`; scrub output with
  `python -m pod.scrub`. Full recipe, prices and pitfalls: `docs/GPU_RUNS.md` ("How we run a pod today").
- Never print or cat credential files (`~/.runpod`, `~/.kaggle`, `.env`); read one value by name.
- Other projects run pods on this account. Only terminate pods named `rp-job*` that we created.
- Cap is 10 USD in total; the account limit cannot be lowered. Report cost after every job. Spend state is
  in the auto-memory file `runpod-spend-tracking.md`, not in the repo.
- A pod's Python is not Kaggle's image: keep the env gate (`pod/env_check.py`, `pod/test_env.sh`) on every GPU job.
- `rp up` reuses a pod with the same name: terminate the old pod first, and give parallel pods their own
  `RP_POD_NAME` and `RP_STATE_FILE`.
- A failed `runpodctl pod list` (the API times out now and then) means "unknown", never "pod gone".
- Competition data goes to a pod with `runpodctl send` from this machine. The scratch dir under `/tmp` can be
  wiped between sessions: rebuild `data.tar` from the pack list in `docs/GPU_RUNS.md`.

## Conventions
- Branch per slice off fresh `main`, PR only, CI green before merge. CI can queue for minutes.
- A bug or flake gets a failing test first. Keep diffs small: delete what a change supersedes.
- Never commit secrets, data, `*.zip`, or LoRA weights. `make check` must pass before push.
- Decisions a future agent would re-litigate get an ADR in `docs/adr/`.
- Delete worktrees and merged branches when a task ends; list anything left running in the summary.
- Update README and this file in the same PR that changes what they describe.
