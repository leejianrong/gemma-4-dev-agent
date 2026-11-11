# GPU runs and the gold-patch check: feasibility (GEM-88)

Design only. Nothing here was launched and no money was spent. Written 2026-11-09.
Every claim carries a tag: **[docs]** read in the harness guide or our repo, **[measured]** we
looked it up or ran it, **[guess]** an estimate that a real attempt must confirm.

## Short answers

1. **Can `pod/eval_runner.py` run on a RunPod GPU pod?** Yes in principle, with one change of
   mindset: the runner is a Kaggle kernel script, so the pod must fake three Kaggle paths and
   install what Kaggle's image already has (torch 2.10, litellm). Use the subprocess sandbox, not
   Docker. The first real attempt will probably need one debug round.
2. **Cheapest GPU that fits:** one 48 GB card (A40, about 0.59 USD/h secure). The weights alone are
   21.7 GiB, so a single 24 GB L4 cannot hold them. An A100 80 GB (1.79 USD/h secure) is the safe
   second choice.
3. **Can we check whether the 9 inconclusive baseline tasks are a sandbox gap, without a model?**
   Yes, for free, on this machine. The grading sandbox image is public (Dockerfile in the
   competition files), `verify_task` accepts any patch, and the evidence so far already points at
   a gap: the missing test packages are not in the official wheel cache.

## 1. What the eval runner needs

| Need | Detail | Tag |
|---|---|---|
| Python 3.12 | The runner refuses wheels built for another Python (`cp312` tags). | [docs] `er_wheel_python_mismatch` |
| GPU | Compute capability 8 or higher (bf16). The runner picks tensor parallel 4, 2 or 1 from the GPU count. | [docs] `er_main_impl` |
| Wheelhouse | Kaggle dataset `metric/gemma-4-developer-agent-wheelhouse`: 41 wheels, 0.82 GiB. It holds vllm 0.19.1, google-adk 1.36.1, adk_submission 0.2.13, swegemma 0.2.11, adk_eval_core, transformers 5.13.1, flashinfer. | [measured] Kaggle file listing |
| Not in the wheelhouse | torch and litellm. On Kaggle they come from the base image. vllm 0.19.1 needs `torch==2.10.0` and `torchvision==0.25.0`. | [measured] listing plus PyPI metadata |
| Download wheelhouse | `kaggle datasets download metric/gemma-4-developer-agent-wheelhouse -p DIR --unzip` | [docs] CLI help |
| Model | `google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`: one 23.27 GB `model.safetensors` plus small config files. That is 21.7 GiB of weights before any KV cache. | [measured] Kaggle file listing |
| Download model | `kaggle models instances versions download google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2 -p DIR --untar` | [docs] CLI help |
| Data | `tasks.jsonl` 2 MiB, `graphs/` 402 MiB, `embeddings/` 446 MiB, `wheels/` 27 MiB (test dependencies), `snapshots/` about 165 MiB per task (5 GB for 30 tasks). | [measured] listing |
| Sandbox | The runner defaults to `subprocess`, and the baseline run used it (test logs show `/tmp/swegemma_sandbox_*`). | [measured] |
| Docker on a pod | Not expected to work: a RunPod pod is itself a container without a Docker daemon. | [guess] |
| Host tools for subprocess mode | `git` and `patch` on the host, and permission to create virtual environments. | [docs] harness guide 4.1 |

**Hard-coded Kaggle paths.** The runner reads the wheelhouse from
`/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse` and the model from
`/kaggle/input/models/google/gemma-4/other/<model>/2`. These are constants, not settings. On a pod,
download to a normal folder and symlink to those paths. [docs] `ER_WHEELHOUSE`, `ER_MODEL_ROOT`.

**Environment variables.**
- Set by the runner itself (`ER_ENV`): `TRANSFORMERS_OFFLINE=1`, `VLLM_NO_USAGE_STATS=1`,
  `VLLM_WORKER_MULTIPROC_METHOD=spawn`, `VLLM_ENGINE_READY_TIMEOUT_S=1200`, `LOCAL_API_KEY=EMPTY`,
  `OPENAI_API_KEY=EMPTY`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` and a few telemetry
  switches. [docs]
- Read by the kernel wrapper: `DATA_DIR` (default the Kaggle competition path), `OUT_DIR` (default
  `/kaggle/working`), `MIN_FILES`. [docs] `kaggle/build_kernel.py`
- Fixed at build time into the kernel: `EVAL_TASKS`, `EVAL_RUN_ID`, `EVAL_MODEL`,
  `EVAL_CONCURRENCY`, `EVAL_MAX_MIN`, `EVAL_SEED`, `EVAL_SANDBOX`, `EVAL_PROBE`, and
  `SUBMISSION_DIR` for the bundle. [docs]
- The wrapper's preflight needs at least 100 graph files and 100 embedding files in `DATA_DIR`. [docs]

**Outputs and our run contract.** The runner writes `task_results.csv`, `raw_results.jsonl`,
`summary.json`, `report.json`, `raw/` (the harness results: patches, test outputs, traces) and
`our_submission/`. Its task columns are identical to `TASK_COLUMNS` in `analysis/runs.py`
[docs]. The remaining steps are unchanged from the Kaggle route: `analysis/harness_adapter.py`
turns `raw/traces` into contract traces, `scripts/log_run.py` adds the `runs.csv` row, and
`analysis.runs.validate_dir` checks the folder. [docs] `docs/RUN_CONTRACT.md`

## 2. A pod job, step by step

Same style as `pod/job.sh` and `pod/pod_cmd.py`: scripts travel inside the start command,
gzip plus base64, with the dead-man's switch first. [docs] runpod-jobs skill

1. **Launch** with `rp up` and `RP_COMPUTE_TYPE=GPU`, one GPU of the chosen type, a container disk of
   at least 120 GB (model 22 GB, wheelhouse 1 GB, data 7 GB, torch and CUDA libraries about 8 GB,
   room to spare), `RP_MAX_LIFETIME_SECS` set to the planned run plus 40 minutes. [guess] on sizes
2. **Bootstrap:** Python 3.12 image with `git`, `patch`, `curl`. Install the Kaggle CLI and `six`.
   `pod/job.sh` already does the CLI part. [measured] the `six` bug cost one pod attempt
3. **Download** in this order, smallest first, so a failure costs little: `tasks.jsonl`, graphs,
   embeddings, `wheels/`, snapshots for the chosen tasks, the wheelhouse, then the model.
   `scripts/fetch_data.py` needs a `wheels/` entry first (it does not fetch that folder today).
4. **Install:** `torch==2.10.0`, `torchvision==0.25.0`, `torchaudio==2.10.0` and `litellm` from
   PyPI (the pod has internet), then `pip install --find-links WHEELHOUSE vllm==0.19.1 google-adk
   swegemma adk-submission adk-eval-core`. The runner then re-installs the wheelhouse itself with
   `--no-deps --force-reinstall`. [guess] that this order resolves cleanly
5. **Symlink** the two Kaggle paths to the downloaded wheelhouse and model.
6. **Run** the kernel built by `make kernel-eval` with `SUBMISSION_DIR`, `EVAL_TASKS`, and
   `EVAL_SANDBOX=subprocess`, with `DATA_DIR` and `OUT_DIR` pointing at the pod folders.
7. **Return** the results the way `job.sh` does: tar `OUT_DIR`, `runpodctl send`, print
   `RP_ARTIFACT_CODE`, then `rp relay-get`. Pull the artifact before `rp down`.
8. **Verify** that `pod list` no longer shows our pod, then log the cost against the 10 USD cap.

## 3. GPU choice and cost

Prices are from `runpodctl gpu list` on 2026-11-09 [measured]; every stock status read "Low" or
"none", so availability is a risk of its own.

| GPU | VRAM | Price per hour | Fits the 31B w4a16? |
|---|---|---|---|
| A40 | 48 GB | 0.59 secure | Yes: 21.7 GiB weights, about 20 GB for KV cache at 0.90 utilisation [guess] |
| A100 SXM | 80 GB | 1.39 community, 1.79 secure | Yes, with room for concurrent tasks |
| H100 SXM | 80 GB | 2.69 community, 3.99 secure | Yes; not worth the price for this load |
| 4 x L4 (Kaggle's setup) | 4 x 24 GB | 4 x 0.59 secure | Yes with tensor parallel 4; pricier than one A100 |

Kaggle's own runs use 4 x L4 with tensor parallel 4, because the runner picks 4 when it sees 4 GPUs.
[docs] A single card is simpler (tensor parallel 1) and avoids the PCIe traffic between L4 cards.

**Time and cost per 30-task run.** We measured 5.3 min per task and 2.65 h per 30 tasks on 4 x L4
with one task at a time. [measured] The rest is a guess until a pod run exists:

| GPU | Hours for 30 tasks | Plus start-up | Cost per 30-task run |
|---|---|---|---|
| A40 | 3 to 4 [guess] | 0.5 | about 2.1 to 2.7 USD |
| A100 secure | 1.5 to 2.5 [guess] | 0.5 | about 3.6 to 5.4 USD |
| A100, 4 tasks at once | 0.6 to 1 [guess] | 0.5 | about 2 to 2.7 USD |

Start-up is mostly the 23 GB model download. We saw 2 to 21 MB/s from Kaggle while fetching the
competition data, so 18 minutes to 3 hours. [measured] range. A network volume would pay that cost
once (about 1.7 USD per month for 25 GB, by our earlier estimate); `rp` cannot create one yet.

**Budget reality.** The 10 USD cap buys 2 or 3 replicates at best. The ablation plan wants about 20
GPU-hours for 3 replicates of 2 arms (`docs/ABLATION_PLAN.md`), which is 12 to 36 USD on a pod.
The pod route is good for the probe and one or two replicates. The bulk of the replicates should
stay on Kaggle's free quota, or the cap needs raising.

## 4. Unknowns, cheapest to resolve first

| # | Unknown | How to resolve it | Cost |
|---|---|---|---|
| 1 | Does the install order in step 4 resolve on Python 3.12, and does `import litellm, torch` work? | A CPU pod (0.12 USD/h) or a local Python 3.12 container; no GPU needed to import. | Under 0.20 USD |
| 2 | Does `import swegemma` need `torchvision` and `accelerate` at import time? (It lists them as requirements.) | Same CPU or local check as 1. | Free to 0.20 USD |
| 3 | How fast does Kaggle serve the 23 GB model to a pod, and does the account get throttled (HTTP 429, seen on 9 Nov)? | Download on a CPU pod while doing 1; use the main login or a fresh token. | About 0.50 USD |
| 4 | Does vLLM 0.19.1 start on an A40 (compute 8.6) with these wheels, and how long does it take? | One GPU attempt of 30 minutes, ending after the probe task. | 0.30 to 1 USD |
| 5 | Does a skill script see `/workspace`, and do its calls count against the tool budget (GEM-79)? | The same GPU attempt as 4, using `experiments/probes/skill_probe`. | Included in 4 |
| 6 | Real throughput on one GPU, and whether 4 tasks at once is safe with 2 vCPUs per sandbox. | A 5-task run at concurrency 1, then 4. | 1 to 2 USD |
| 7 | Do pod hosts have a driver new enough for CUDA 12.8 (the wheels are `cu128`)? | Filter by allowed CUDA version when creating the pod; read the pod's `nvidia-smi` in the first log. | Free if the filter works |
| 8 | Is the Kaggle base image (`gcr.io/kaggle-private-byod/...`) pullable on RunPod? | Try once on a CPU pod. We expect not. | Under 0.05 USD |

Unknowns 1 to 3 should all be cleared on one CPU pod before any GPU hour is paid for.

## 5. The gold-patch check

**Question.** Are the 9 baseline tasks whose test run errored before any assertion a gap in our
sandbox, or does the official sandbox fail them too? [docs] `docs/QUESTIONS.md` and `analysis/failure_classes.py`

**What we learned for free.**
- The grading image is public. The competition files include `docker/Dockerfile.public` and
  `Dockerfile.sandbox`: `python:3.13-slim`, plus `git`, `patch`, `protobuf-compiler`, `pigz`,
  `pytest`, `pytest-timeout==2.1.0` and the build backends. The public variant copies the folder
  `wheels/` into `/wheels`. [measured] files read
- The harness runs tests with no network, 4 GiB memory and 2 vCPUs. [docs] harness guide 4.1
- The wheel cache holds 41 distinct packages and none of `inline_snapshot`, `dirty_equals`,
  `pytest-httpbin` or `trustme`. [measured] listing of `wheels/`
- Our 30 baseline test logs show `inline_snapshot` missing in 9 logs, `dirty_equals` in 1, and the
  `httpbin` fixture recursion error in 7 (requests tests, where the plugin is absent). [measured]
- The sandbox setup script injects no test dependencies on its fast path; it only adds workspace
  paths and writes `pytest.ini` and `conftest.py`. [docs] `sandbox/setup.py`
- A task counts as resolved only if pytest exits 0, the JUnit file shows zero errors and zero
  failures, and every required test passed. [docs] harness guide 8.2

**Reading.** These tasks very likely cannot be resolved in the official sandbox either, so every
entry scores 0 on them. This is an inference from the wheel list, not a proof. If it holds, the
requests tasks (13 in the public set) are mostly unscoreable, and the 6 requests tasks in the
dev subset are dead weight. [guess] until the check below runs

**The decisive test.** Feed the *gold* patch to the grader. If the gold patch fails on the 9 tasks
the same way, they are intrinsic gaps. If it passes, our agent's patch was the cause.

| Route | Fidelity | Cost | Catch |
|---|---|---|---|
| **A. Local venv plus the real image (recommended)** | Highest: official Docker backend, official image | Free | Install swegemma and its imports on this machine |
| B. Kaggle CPU kernel with the wheelhouse | Medium: subprocess sandbox on Python 3.12, not 3.13 | Free | The Kaggle queue |
| C. RunPod CPU pod | Medium: no Docker, so subprocess sandbox | About 0.10 USD | Same difference as B |

**Route A in detail.**
1. Build the image `swebench-sandbox:latest` locally from `Dockerfile.public`, `imp.py`,
   `telnetlib.py` and `wheels/` (all under 30 MB, from the competition files). Build needs network
   once; runs use `--network none`.
2. Create a Python 3.12 venv with `swegemma`, `adk_eval_core`, `adk_submission` and `google-adk` from
   the wheelhouse plus CPU-only PyPI dependencies. This runs the competition's harness code, not
   repo code. [guess] on how many dependencies it pulls
3. Call `verify_task(docker, config, task, snapshot_path, agent_patch=task.patch)` with the Docker
   sandbox manager. Its signature is `verify_task(docker, config, task, snapshot_path, *,
   base_snapshot_path, patch_path, fast_path=True, agent_patch='', ...)`. [measured] read from the
   swegemma 0.2.11 wheel. No model and no GPU is involved.
4. Run it for the 9 inconclusive tasks and 3 baseline-resolved tasks as controls (the controls
   should pass with their gold patch too). Time is seconds to a minute per task.
5. Record only counts ("gold patch passes on k of 9"). Per-task logs stay under `data/`.

**What we must not do.**
- Do not publish or commit per-task results, logs, patches or task ids with outcomes (rules 4b).
- Do not run repo tests on the host Python. They run in the container, or the check does not run.
- Do not run `pip install` of repo dependencies on the host; the image and the wheel cache are the
  only sources, as in the official sandbox.
- Do not widen the wheel cache "to make tasks pass". That would test a sandbox the grader does
  not use.

## 6. Proposed next cards

1. Clear unknowns 1 to 3 on one CPU pod (or locally), about 0.30 USD.
2. Run route A of the gold-patch check; decide whether the requests tasks leave the dev subset.
3. One GPU attempt on an A40 that ends after the GEM-79 skill probe (unknowns 4, 5, 7).
4. Add `wheels/` to `scripts/fetch_data.py` and a `pod/gpu_job.sh` after step 3 works.

## 7. Gold-patch check result (GEM-89, 2026-11-10)

Aggregates only (rules 4b). Route A was run locally and cost nothing: the public `Dockerfile.public`
image with the public `wheels/` cache (115 files), `--network none`, and `swegemma` 0.2.11 in a
throwaway Python 3.12 venv (`analysis/gold_check.py`). [measured]

**Setup facts.**
- `swegemma` imports without torch, vllm or litellm. It needs `google-adk`, `google-genai`,
  `docker`, `pydantic`, `pyyaml`, `rich`, `numpy`, `networkx`, `cachetools`, `python-dotenv`, plus the
  `adk_eval_core` and `adk_submission` wheels. [measured]
- The harness needs the sandbox `setup.py` (env var `KAGGLE_SANDBOX_DIR`) and a host wheels folder.
  Without the wheels folder no test dependency reaches the container. [measured]
- The wheel code says the full cache is about 1.7 GB; the public one is 27 MiB. The grader's cache
  (`.../metric-data/sandbox/wheels`) is not public. [read in swegemma source]

**Results on 12 tasks (the 9 inconclusive baseline tasks and 3 baseline-resolved controls).**

| Path | Controls resolved | Inconclusive tasks resolved | What failed |
|---|---|---|---|
| `verify_sample_task_airgapped` (official sweep) | 3 of 3 | 0 of 9 | 6 missing test module; 3 test files not found (the sweep applies the test patch differently, so those 3 say nothing) |
| `verify_task` with the gold patch (the grading function) | 1 of 3 | 0 of 9 | 8 missing test module, 1 other; 2 controls hit a collection error |

- The collection errors come from the cache, not the tasks: the harness injects the newest wheel of each
  package, here `starlette` 1.6.0, which older fastapi code cannot import. Our Kaggle run resolved
  the same controls, so the local setup differs from that run in a way we did not find. [measured, cause guess]
- A control that fails means this check is not validated. So 0 of 9 does **not** show that every entry
  scores 0 on those tasks.

**Static count (no code run).** Test patches of 29 of the 129 public tasks (fastapi 21 of 67, requests
8 of 13) mention `inline_snapshot`, `dirty_equals` or `httpbin`, none of which is in the public cache.
This is a lower bound: it misses modules imported by existing test files and conftests. [measured]

**Reading.** In every environment we can build from public files, those tasks cannot be judged. Whether
the leaderboard grader has more wheels is unknown. Keep the 9 tasks out of the dev subset, since our own
runs use the public cache, and write "unscoreable in our runs" in the paper, not "unscoreable for every
entry". I did not run the 30 optional extra tasks: with the controls failing, an extrapolation would
mean nothing. [guess]

## 8. GPU route prep (2026-11-11)

Nothing here launched a GPU pod. One CPU pod ran for about 5 minutes. [measured]

**Unknowns 1 and 2: resolved.** In a throwaway `python:3.12-slim` container with the real wheelhouse,
`pod/gpu_setup.sh` installed cleanly in 13 minutes (7 GB of site-packages) and the imports worked.
Resolved versions: torch 2.10.0 (CUDA 12.8 build), torchvision 0.25.0, torchaudio 2.10.0,
litellm 1.109.0, vllm 0.19.1, google-adk 1.36.1, swegemma 0.2.11, adk-submission 0.2.13,
transformers 5.22.2, numpy 2.2.6. `import litellm, torch`, `from adk_submission import VllmServer`
and `from swegemma.evaluate import Evaluator` all succeed, so unknown 7's wheel side is settled too
(the driver side still needs a pod). The runner later reinstalls the wheelhouse with `--no-deps`, which
moves transformers to the wheelhouse's 5.13.1; that step was not run here. [measured]

**Unknown 3: download speed, mostly resolved.** A CPU pod pulled the model from Kaggle with the
main account's token for 240 s: 8 to 12 GiB arrived (the file is preallocated in 4 GiB steps, so
the exact figure is a range), about 35 to 50 MiB/s, and no HTTP 429. The 23 GB model should take
8 to 11 minutes. Cost 0.02 to 0.05 USD. [measured] The earlier 2 to 21 MB/s was Kaggle's data
download to a laptop and an older pod; this route was faster.

**What changed in the repo.**
- `pod/eval_runner.py` reads the wheelhouse and model folders from `ER_WHEELHOUSE_DIR` and
  `ER_MODEL_ROOT_DIR`; the Kaggle mounts stay the defaults. The data and output folders were already
  `DATA_DIR` and `OUT_DIR`.
- `pod/gpu_setup.sh`: the pinned install order above, with a version and import check.
- `pod/gpu_run.py`: the step `pod/job.sh` runs instead of the analysis on a GPU pod. It downloads the
  wheelhouse and model, runs `gpu_setup.sh`, then the built eval kernel with the four env vars.
- `pod/pod_cmd.py` accepts `@file` arguments to ship `kernel.py` and `gpu_setup.sh` inside the start
  command. `pod/job.sh` fetches `wheels/` (the tests' dependency cache) when `WANT_SNAPSHOTS=1`, and
  skips its graph-analysis sanity check for other reports. `scripts/fetch_data.py` fetches `wheels/`
  with snapshots too.
- Rehearsed free: `job.sh` into `gpu_run.py` into a stub kernel against the fake Kaggle and relay
  CLIs: stages, env wiring, report and relay code all worked. A real kernel was not run.

**How to run one 36-task replicate (not yet run).** Build the kernel, build the start command (it
embeds the Kaggle token by name from `.env`; never print it), launch, pull the artifact, tear down:

```
IDS=$(python3 -c "import json;print(','.join(json.load(open('data/dev_subset.json'))['ids']))")
SUBMISSION_DIR=experiments/bundles/tests_v1 EVAL_TASKS="$IDS" EVAL_RUN_ID=dev-a3-r1-pod \
  EVAL_SEED=1 EVAL_MAX_MIN=480 python3 kaggle/build_kernel.py leejianrong eval
export RP_POD_IMAGE=python:3.12 RP_COMPUTE_TYPE=GPU RP_GPU_TYPE="NVIDIA A40" \
  RP_CONTAINER_DISK_GB=150 RP_MAX_HOURLY_USD=0.80 RP_MAX_LIFETIME_SECS=21600
RP_JOB_CMD="$(python3 pod/pod_cmd.py pod/gpu_run.py @pod/gpu_setup.sh @kaggle/eval_kernel/kernel.py \
  WANT_SNAPSHOTS=1 SNAP_IDS=$IDS DISK_PERCENT=120 MAX_MIB=12000 T_DL=3000 T_ANALYZE=18000)" \
  ~/.claude/skills/runpod-jobs/scripts/with-runpod-key ~/.claude/skills/runpod-jobs/scripts/rp up \
  >up.raw 2>&1   # then scrub up.raw with pod.scrub before reading it
```

Then `rp relay-get DIR` for the artifact (`out/` holds `task_results.csv`, `summary.json`, traces),
and `rp down`. Check `runpodctl pod list` is empty and log the cost.

**Cost per 36-task replicate.** Start-up is about 0.5 h: model download 8 to 11 min, installs about
13 min, vLLM start about 8 min (494 s on Kaggle). [measured pieces] Run time per task is a guess:
Kaggle's 4 x L4 took 2.8 to 3.0 h for 36 tasks. [measured]

| GPU | Run hours [guess] | Total hours | Price | Cost |
|---|---|---|---|---|
| A40 48 GB | 3 to 4 | 3.5 to 4.5 | 0.59 | about 2.1 to 2.7 USD |
| A100 80 GB secure | 1.5 to 2.5 | 2 to 3 | 1.79 | about 3.6 to 5.4 USD |

The 10 USD cap allows two A40 replicates, or one A100 replicate plus a probe. Before the first
paid run, set `RP_MAX_HOURLY_USD` above the card's price, as in the command above.

**Remaining GPU unknowns.** 4 (vLLM 0.19.1 on an A40), 5 (skill sees `/workspace`: answered by A38
already), 6 (real throughput on one GPU), 7 (host driver for CUDA 12.8) and 8 (the Kaggle base image
on RunPod: unnecessary, we use `python:3.12`). A first run should watch the logs for vLLM startup
and the tensor-parallel setting (the runner picks 1 for one GPU).

## 9. First GPU probe (2026-11-11)

One pod, 2 dev tasks, baseline bundle, 31B w4a16 on one card. The pipeline worked end to end and the
pod was terminated and verified gone. [measured]

- **Capacity.** Spot pods are no longer offered. The A40 is no longer in `runpodctl gpu list`. On
  community cloud, no 48 GB card had stock (all listed as "Low"). On secure cloud an RTX 6000 Ada
  (48 GB, 0.99 USD/h, driver 595.91.07) was free; the RTX A6000 (0.59 USD/h) was not. Launch with
  `RP_INTERRUPTIBLE=false RP_CLOUD_TYPE=SECURE` and a list of acceptable cards.
- **Unknown 4, vLLM on one 48 GB Ada card: works.** vLLM 0.19.1 with tensor parallel 1 was up after
  198 s (494 s on Kaggle's 4 x L4). The weights took about 21 GB and vLLM used 44 GB of 49 GB.
- **Unknown 7, driver for CUDA 12.8: works** (driver 595.91.07).
- **Unknown 6, throughput.** 2 tasks took 270 s and 219 s (28 tool calls each, one hit the tool
  budget). Kaggle's 4 x L4 averaged 4.6 to 5.0 min per task, so this card is about 15 to 25% faster
  per task. Two tasks is a small sample.
- **Start-up measured:** data 3 min, model download 4.7 min (283 s), installs about 6 min, vLLM 3.3 min.
  Total about 17 min before the first task.
- **Cost of one 36-task replicate on this card:** about 17 min + 36 x 4.1 min = 2.8 h, so about 2.8 USD
  at 0.99 USD/h. [estimate from 2 tasks]
- **Probe cost:** the balance fell from 15.156 to 14.795 USD, 0.36 USD (it can lag the pod's last
  minutes). The pod ran about 35 minutes at 0.99 USD/h, so about 0.58 USD is the upper figure.
- **Fixes found:** the job's outer "no progress" warning counts only some log lines, so it fires
  during a healthy eval; the kernel's own `HEARTBEAT` line is the signal to trust.

## 10. The pod's task environment is not Kaggle's (2026-11-12)

A first full GEM-31 replicate on an L40S (6 minutes per task) was stopped after 3 of 36 tasks because
the agent reported `pytest is not installed in the environment`. [measured, from the pod log]
The subprocess sandbox builds a venv with `system_site_packages` and adds the host's site-packages
(`swegemma/sandbox/subprocess.py`), so the host Python must already hold pytest and the repositories'
test dependencies. Kaggle's base image does; our `python:3.12` pod plus `pod/gpu_setup.sh` does not.
- The 2-task probe in section 9 had the same gap, so its 0 of 2 resolved is not evidence about the agent.
  Its throughput and start-up numbers stand.
- Any pod run needs the host environment fixed first, and a check before the eval that a known-solvable
  task resolves with its gold patch. A failed run cost about 2.7 USD in total (pods that waited for the
  upload, the failed download attempt and this one).
- Comparison with the Kaggle runs also needs the same GPU class: this card was about 30% slower per task
  than Kaggle's 4 x L4, and the 8-minute task limit is wall-clock.
