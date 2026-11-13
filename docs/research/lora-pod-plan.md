# E4B LoRA: pod plan

Status: draft, nothing run. Follows `lora-feasibility.md`. Date: 2026-11-13.

## Why this is open again

The terms question (rules 4b) is no longer treated as a blocker. 4a allows any use of the data, adapters
go only to the host inside `submission.zip`, and the rules accept adapters. Two conditions: never publish
adapter weights (public notebook, Kaggle dataset), and ask on the forum before the final submission.

The other blockers stand, and the data one is the hard one.

## The data problem (decides whether this is worth a pod)

- **Our resolved traces are all dev tasks.** The 56 resolved 31B runs cover 17 tasks, all inside the 36
  dev tasks we judge on. Training on them and scoring on the same tasks measures memorisation. Split by
  repo as the dev protocol does, and the training set shrinks again, probably below 10 tasks.
- **E4B's own resolved runs are fewer still** (5 of 36 per replicate).
- **Traces lack thinking**, so we would train on visible text and tool calls only. The Gemma 4 chat
  template bug (HF discussion 115) is untested, so the training format is a guess.
- **Synthetic tasks are the only unlimited source** (about 7 to 15 usable per repo at 3 sites, A48), but
  trajectories on them need a model run first. 31B on a pod costs about 1.1 USD/h.

So a pod run now would train on a handful of trajectories. Expect it to teach format, not skill. That may
still be the useful claim: a small edit-refusal gain, not a resolution gain.

## Stages, each gated

| # | Stage | Where | Cost | Pass if |
|---|-------|-------|------|---------|
| 0 | Import test: `peft`, `transformers`, `compressed-tensors` resolve on the pod image; one forward pass with a LoRA on the E4B `w4a16-ct` base | CPU pod or 16 GB GPU, 15 min | under 0.15 USD | adapter attaches, loss is finite, and a saved `adapter_model.safetensors` loads in the pre-flight (`make check`) |
| 1 | Build the set (laptop, no GPU): resolved 31B and E4B trajectories on non-held-out repos, plus synthetic tasks run through E4B | laptop | 0 | count, and a held-out repo list written down before training |
| 2 | Train, rank 16, 1 to 2 epochs | 16 to 20 GB card at 0.24 to 0.28 USD/h | about 0.3 USD | loss falls, no NaN |
| 3 | Eval: one 36-task replicate of the adapter vs the existing E4B v2 and v3 rows | same card | about 0.5 USD | see below |

Total about 1 USD against about 1.8 USD left (check `runpodctl user` for the real balance before stage 0).
Stages 0 and 1 are the only ones worth starting without a go on the whole thing.

## Stage 1 result (2026-11-13, laptop, aggregates only)

**Held-out repos, written before any training data is built: `Textualize/rich`, `psf/requests`, `encode/httpx`.**
Train, if ever, on `fastapi/fastapi` only. Judge on the held-out repos (rich 48 tasks, requests 13, httpx 1).

Resolved 31B task-runs (dev-a0/a2, r1 and r2, 144 runs): fastapi 52 resolved over 16 distinct tasks;
requests 4 over 1 task; httpx 0. Rich has no 31B traces at all. After the repo split the training set is
**52 runs over 16 fastapi tasks**, and the earlier count says 12 of those tasks are always solved (easy,
median gold patch 5 lines). Dev scoring on fastapi would be memorisation, so the only fair eval is the
held-out repos, where E4B has no baseline on rich yet (an extra run, not in the budget above).

**Verdict: the set does not justify the stage 0 pod test.** 16 tasks of one repo, mostly tasks the base
model already solves, is below the 491-trajectory floor of the published fine-tunes (lora-feasibility.md)
by a factor of 30 or more, and the held-out eval needs a rich baseline we have not paid for. Stage 0
(about 0.15 USD) answers a mechanics question only; run it when the data side changes (T11 multi-site
synthetic tasks run through E4B or 31B, or budget beyond the cap), not before.

## What counts as a result

Resolution cannot show a difference here (noise 8 to 11 points; a LoRA gain of a few tasks is inside it).
Judge on the log signals from A47: edit-refusal rate (E4B v2: 39% of runs), call of the first edit, calls
per task. Save raw traces this time (T3 could not finish its whitespace test because earlier pod runs did
not). A refusal rate that drops from about 39% to under 20% would be worth a second replicate; anything
else is a stop.

## Checks before spending

1. Stage 0 passes. If it needs more than one fix round, stop: setup risk was the stated reason for no-go.
2. The held-out repo list exists before any training data is built.
3. Pre-flight accepts the adapter, and the zip stays under 3 GiB.
4. Forum question posted (derived weights), reply recorded here.

## Not in scope

31B adapters (48 GB card, about 4x the cost), RL, and any use of a hosted model on real tasks.
