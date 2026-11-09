# Gemma 4 Developer Agent (Kaggle)

Entry for https://www.kaggle.com/competitions/gemma-4-developer-agent. We build `submission/`
(YAML agent config, prompts, skills, optional LoRA) that Kaggle compiles into a Google ADK agent.
Score = % of ~120 hidden SWE-style tasks whose patch passes hidden pytest tests.
Dates: paper (Kaggle Writeup, <=3,000 words) 2026-11-12 23:59 UTC; entry/merge 2026-11-25; final 2026-12-02.
Read `docs/COMPETITION.md` first (rules, limits, dataset). Planning state: `docs/QUESTIONS.md` (A-rows
tag every number in the paper), plan `docs/PLAN.md`, decisions `docs/adr/`, run log `experiments/runs.csv`.

## Status: trust the code over the docs
- `submission/` is the adopted public baseline (flexonafft v2). Public leaderboard 0.18; local 3/30.
- Paper draft: `paper/DRAFT.md`. Active work: localizer skill (`experiments/skills/localize/`), synthetic
  task set (`synthetic/`, `docs/SYNTHETIC_DATASET.md`), ablation plan (`docs/ABLATION_PLAN.md`).
- Board: pandan, GEM = board 45. `pandan comment add CARD --body "..."` needs `--body`; `pandan move`
  prints only a help line even when it works, so verify with `pandan get`.

## Commands
- `make` lists targets. `make setup` installs dev tools and the pre-push hook.
- `make check` = lint + unit tests + submission pre-flight. Same as pre-push and CI.
- `make score-local` scores the localizer on `data/competition` inside an isolated container.
- `make dash` serves the indah dashboards; `make zip` builds `dist/submission.zip`.
- `make rehearse` has one failing scenario (`quiet`) on main that predates our edits; ignore it.

## Rules that are not obvious from the code
- **Competition data terms (rules 4b).** Never publish, commit or upload per-task data: gold nodes,
  hunks, traces, patches, issue text, failure classes by task id. Aggregates, figures and code that
  regenerates them are fine. Paper-track rules say the same.
- **Never run code from downloaded repos or tasks on the host.** Use the container pattern in the
  Makefile (`RUN_ISOLATED`: no network, read-only data, resource limits). Our scripts only parse
  snapshots with `ast`, in memory.
- Data lives in `data/` (gitignored). Fetch with `python scripts/fetch_data.py` (kaggle login, rules
  accepted). Kaggle rate-limits temporary tokens (HTTP 429); the main login worked.
- google-adk, litellm, vllm, swegemma, adk_submission exist only on Kaggle; do not add them to pyproject.
- One base model for every agent. 32,768-token context. read_file: 150 lines / 10k chars.
- Hidden tests come from private repos. No repo-specific prompt tricks; hold out rich when judging a change.
- Kaggle GPU queues can wait hours and the CLI cannot cancel a kernel (`kaggle kernels delete -y` cancels).
- No GPU here (7 GB RAM). Model runs happen on Kaggle L4x4 or a RunPod pod.

## RunPod
- Use the `runpod-jobs` skill and `pod/job.sh`, `pod/pod_cmd.py`; scrub output with `python -m pod.scrub`.
- Never print or cat credential files (`~/.runpod`, `~/.kaggle`, `.env`); read one value by name.
- Other projects run pods on this account. Only terminate pods named `rp-job` that we created.
- Cap is 10 USD in total and the account limit cannot be lowered: report cost after every job.

## Conventions
- Branch per slice off fresh `main`, PR only, CI green before merge. CI can queue for minutes.
- A bug or flake gets a failing test first. Keep diffs small: delete what a change supersedes.
- Never commit secrets, data, `*.zip`, or LoRA weights. `make check` must pass before push.
- Decisions a future agent would re-litigate get an ADR in `docs/adr/`.
- Delete worktrees and merged branches when a task ends; list anything left running in the summary.
- Update README and this file in the same PR that changes what they describe.
