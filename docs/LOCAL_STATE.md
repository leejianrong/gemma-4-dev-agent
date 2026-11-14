# Local state: what is not in git, and how to get it back

Written 2026-11-14 for a move to another machine. Read this after `CLAUDE.md`. Everything below is
absent from a fresh clone. **Nothing here may be committed or uploaded** (competition rules 4b;
`CLAUDE.md`). Run commands from the repo root.

## Do first on a new machine

1. `git clone`, then `make setup` (needs uv and Docker) and `make check`. This needs no data and no GPU.
2. Log in the tools by hand: `kaggle` (accept the competition rules first), `runpodctl`, `gh`, `pandan`.
   Credential files are listed below by name only. Never print them.
3. `python scripts/fetch_data.py --snapshots scored` (about 19 GB, resumable), then `make analysis-image`.
4. Restore the run outputs (section "data/runs") before anything that reads traces.
5. Check the RunPod balance with `runpodctl user` and read the spend note below before renting a pod.

## Gitignored files and where they came from

| Path | Size | Origin | How to get it back |
|---|---|---|---|
| `data/competition/` | 21 GB | Kaggle competition download: `tasks.jsonl`, `graphs/`, `embeddings/`, `snapshots/<id>.tgz`, `wheels/` | `python scripts/fetch_data.py --snapshots scored`. Kaggle answers HTTP 429 to a temporary token after about 260 files; use the main login |
| `data/HARNESS_README.md`, `data/getting-started-gemma-4-developer-agent.ipynb` | small | Kaggle harness guide and starter notebook | `kaggle competitions download gemma-4-developer-agent -f HARNESS_README.md` (the same call with the notebook's file name for the starter notebook) |
| `data/refs/a`, `data/refs/b` | 108 KB | Two public Kaggle notebooks we read: `flexonafft/gemma-4-budget-aware-coding-agent-v2` (our baseline, credit in `docs/ATTRIBUTION.md`) and `gemma-and-the-shape-of-doubt` | `kaggle kernels pull <owner>/<slug> -p data/refs/<x>`. Reference only, nothing depends on them |
| `data/dev_subset.json` | 4 KB | The 36 dev tasks (fastapi 30, requests 5, httpx 1; rich held out) | `python -m analysis.dev_subset` (seeded rule, `docs/ABLATION_PLAN.md`). **Regenerate before any run, the pod data pack lists these ids** |
| `data/labels/task_labels.csv` | 16 KB | Per-task labels | `python -m analysis.labels` (also writes `docs/TASK_LABELS.md`) |
| `data/eda/` | 5 MB | Kaggle CPU kernel `gemma-4-eda-extract` | `make kernel-eda`, push, then `make pull-eda` |
| `data/map/` | 200 KB | Gold-patch to graph-node mapping, kernel `gemma-4-gold-map`. **Holds `gold_nodes.csv` and `gold_hunks.csv`: per-task, never publish** | `make kernel-map`, push, `make pull-map` |
| `data/localize/`, `data/cochange/`, `data/subcheck/`, `data/skill_localize/` | under 2 MB each | Kaggle kernels `gemma-4-localize`, `-cochange`, `-submission-check`, `-skill-localize` | `make kernel-<name>`, push, `make pull-<name>` |
| `data/audit-out/`, `data/audit-out2/`, `data/kernel-out/` | under 100 KB | Early graph audit and explore kernels (`pod/audit.py`, `pod/explore.py`), their logs and reports | `make kernel` builds the explore kernel; the audit builder is `kaggle/build_kernel.py ... audit`. Findings are already in `docs/QUESTIONS.md` |
| `data/score-out/` | 0.5 MB | `make score-local` (localizer scored in the isolated container) | `make score-local` |
| `data/synthetic/multi3`, `multi5` | 149 MB | Synthetic tasks, 3 and 5 edit sites (A48) | `python -m synthetic.fetch CACHE NAME...` then `make synthetic-tasks CACHE=... NAMES="..." SITES=3`; steps in `docs/SYNTHETIC_DATASET.md`. Clones public repos at pinned SHAs, needs network |
| `data/runs/` | 34 MB | Model runs, see below | See below |
| `figures/`, `kaggle/*_kernel/`, `kaggle/writeup_notebook/kernel.py`, `dist/` | small | Generated output | `make eda`, `make kernel*`, `make zip`, `make skill-score-pod` |
| `.env` | tiny | One key: `KAGGLE_API_TOKEN` | Create from your Kaggle account settings. Never print it |
| `~/.kaggle/credentials.json`, `~/.runpod/` | n/a | Tool logins, outside the repo | per each tool's own login (Kaggle account settings for the token, RunPod console for the API key) |

### data/runs

Each folder is one run of the 36 dev tasks, logged in `experiments/runs.csv` (the `run_id` there
names it). Raw traces are task data and stay local.

| Folder | Source | Traces | Re-fetch |
|---|---|---|---|
| `dev-a0-r1`, `dev-a0-r2`, `dev-a2-r1`, `dev-a2-r2`, `gemma-4-eval-runner` | Kaggle L4x4 kernels (31B) | yes (`raw/traces`, 36 each; 30 for the baseline30 run) | `make pull-runs KERNEL=<slug>` while the kernel exists on your account (`gemma-4-dev-a0-r1` etc.) |
| `dev-a3-r1-pod`, `dev-e4b-r1-pod`, `dev-e2b-r1-pod`, `dev-e4bv2-r1-pod`, `dev-e2bv2-r1-pod` | RunPod pods (`pod/job.sh`) | **no, `job.log` only** (`dev-e4b-r1-pod` also has `artifact.tgz`) | **Not recoverable.** The pod is gone. Copy the folders from the old machine, for example `tar czf runs.tgz data/runs` and `scp` |
| `probe/` | Early eval probe | no | Not needed |

Because the pod logs cannot be rebuilt, **copy `data/runs/` across** instead of regenerating it. Save
traces on every new pod run (T3 could not finish its whitespace test for lack of them).

## State that lives outside the repo

- **RunPod spend.** Cap: 10 USD in total for this project; the account spend limit (80 USD) cannot be
  lowered and the account is shared with other projects. Our own jobs came to about 9.0 USD by
  2026-11-12 (`docs/GPU_RUNS.md` sections 12 and 14, estimates). **The balance is exhausted** (0.52 USD
  on 2026-11-13, confirmed by the owner 2026-11-14), so no more RunPod jobs. GPU work moves to a machine
  with a local GPU. A previous auto-memory note held this state; it does not travel.
- **Local GPU.** The harness targets Kaggle's L4x4 and RunPod pods. `pod/gpu_run.py DATA OUT` runs a built
  eval kernel (`make kernel-eval`, `kaggle/build_kernel.py`) and finds data, wheels and weights through
  `DATA_DIR`, `OUT_DIR`, `ER_WHEELHOUSE_DIR` and `ER_MODEL_ROOT_DIR`; point those at local copies. `pod/job.sh`
  is the pod wrapper (data receive via `runpodctl`, heartbeats) and is not needed locally. Keep the env gate
  (`pod/env_check.py`) and save raw traces. Weights and the wheelhouse come from Kaggle (`docs/GPU_RUNS.md`).
  Set `ER_VLLM_GPU_UTIL` (default 0.90, as on Kaggle) below the free share of VRAM when other processes hold
  some, e.g. 0.6 on a 16 GB laptop GPU with 5.5 GB in use. Not yet tried locally: expect to debug paths and `EVAL_TP`.

## Working rules that survive the move

`CLAUDE.md` holds them. Three that cost time before: never run code from downloaded repos on the host
(use the Makefile container pattern), never print credential files (extract one value by name), and a
pod's Python is not Kaggle's image (keep the env gate on every GPU job).

## Where the work stands

See `docs/research/README.md` ("Where we stood") and `docs/research/tasks.md` for the open list.
Short version: no GPU quota left; `e4b_v3` and `e2b_v3` have no run row yet; the LoRA plan
(`docs/research/lora-pod-plan.md`) is stopped at stage 1 because the training set is 52 runs over 16
fastapi tasks.
