# Gemma 4 Developer Agent (Kaggle)

Entry for https://www.kaggle.com/competitions/gemma-4-developer-agent. We build `submission/`
(YAML agent config, prompts, skills, optional LoRA) that Kaggle compiles into a Google ADK
agent. Score = % of ~120 hidden SWE-style tasks whose patch passes hidden pytest tests.
Final deadline 2026-12-02; entry/merge 2026-11-25. Planning state: `docs/QUESTIONS.md`
(PLAN.md and SLICES.md not written yet, six forks await the owner's answers).

## Status: trust the code over the docs
Scaffold only. `submission/agent.yaml` is a placeholder from data/HARNESS_README.md (Kaggle docs, gitignored) and has never
run through `adk_submission`. Nothing has been scored.

## Commands
- `make` lists targets. `make setup` installs dev tools and the pre-push hook.
- `make check` = lint + unit tests + submission pre-flight. Same as pre-push and CI.
- `make zip` builds `dist/submission.zip` (agent.yaml at archive root).

## Facts that are not obvious from the code
- No GPU here (7 GB RAM). Model-in-the-loop runs happen on Kaggle L4x4 (internet off) or a
  rented pod. Local = editing, packaging, docker sandbox checks.
- google-adk, litellm, vllm, swegemma, adk_submission exist only on Kaggle. Do not add them to
  pyproject. `scripts/submission.py` mirrors the documented limits only.
- One base model for every agent. 32,768-token context. read_file: 150 lines / 10k chars.
- Hidden tests come from private repos; public data is fastapi, rich, requests, httpx. No
  repo-specific prompt tricks; hold out one repo when judging a change.
- Competition data (~21 GiB) lives in `data/` and is gitignored. Download over wired/unmetered
  links only; ask first.

## Conventions
- Branch per slice off fresh `main`, PR only, CI green before merge.
- A bug or flake gets a failing test first.
- Never commit secrets, data, `*.zip`, or LoRA weights. `make check` must pass before push.
- Decisions that a future agent would re-litigate get an ADR in `docs/adr/`.
