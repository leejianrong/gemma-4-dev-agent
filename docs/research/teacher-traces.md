# Teacher traces with semula and Haiku

Status: pilot done 2026-11-21 (5 tasks, no GPU). Owner approved teacher traces for this competition (A50).

## How it runs

```
our harness (container, internal docker network) --OpenAI calls--> semula container
semula parks each call --> scripts/teacher_worker.py (host) --> `claude -p --model haiku --tools ""`
```

- semula is the owner's mock-LLM server (`~/projects/abang-ai/semula`, image `ghcr.io/leejianrong/semula:0.6.0`; the
  `semula:dev` image is older and lacks `pending --wait`). Use a fresh volume per run so no recorded answer replays.
- `ER_EXTERNAL_API_BASE=http://semula:8080/v1 LOCAL_GPU_NETWORK=<internal net> pod/local_run.sh run NAME` skips vLLM, the
  weights and the CUDA check, and joins the container to an `--internal` network that holds only semula.
- Haiku has every tool off and an empty working directory. The agent's own tools run in the task container, so no
  repository code ever runs on the host.
- Tasks must be synthetic or non-competition (rules 4b): the request carries the task text.
- The bundle copy needs `max_time_minutes` raised (20): each Haiku turn costs about 9 s on the task clock.

## Pilot result (5 S3 tasks, e4b_v2 bundle, concurrency 2, 822 s)

120 model turns, about 9 s each (89 tool calls, 31 text replies). 3 of 5 tasks submitted a patch; 2 ended with Haiku
writing text and no edit (one hit the 28-call cap, one stopped early). **0 of 5 resolved**, but see A61: the local grader
could not import the package in 3 of the 5 tasks, so the count says nothing about Haiku.

## 30-task run (A63)

14 of 30 resolved (47%), 28 of 30 patched, 1,945 s, concurrency 3. The instruction now says to edit and call
`submit_patch` before any text. Open problem: some tasks fail with "Required test node did not pass" although every test
in the log passes, so validate tasks by their required node, not only by "gold fixes a test".

## Training data (built 2026-11-22)

`PYTHONPATH=. python3 -m analysis.teacher_dataset OUT TOOLS_JSON RUN_DIR... --val-repo sqlparse` writes `train.jsonl` (local only,
never git) and aggregate `stats.json`. 97 resolved trajectories, all kept: 55 clean and 42 repaired. Repair removes each
text-only assistant turn that the harness answered with a "Please continue" nudge (Haiku wrapped a valid call in stray tags):
73 turns. Filters: needs `submit_patch` and an edit, at most 28 calls, no call repeated 3 times in a row. Median 7 calls,
first edit at call 4, about 5.7k tokens (longest about 17k, so everything fits 32k). The tool schemas are rebuilt from the
harness function signatures, close to but not the exact ones the model saw. Validation repo: sqlparse (12 records).

## Next

1. Validate tasks by required node (A63), then run the rest of S1/S3 for more trajectories.
2. Keep only trajectories whose patch passes the hidden tests under the gate-validated environment.
3. Convert semula's call log plus the harness trace into chat-format training data (not built yet).

## First LoRA and its evaluation (2026-11-23)

`scripts/lora_train.py` trains a LoRA on the E4B base from the records above (`pod/train_job.sh` queues it
through pueue; `TRAIN_DATA` picks the data folder). The base is a compressed-tensors int4 checkpoint that
PEFT cannot wrap, so the linears are replaced by layers that dequantise on the fly (packed weights saved,
re-dequantised in backward) with float32 LoRA A and B. Targets: q, k, v, o, gate, up, down of the language
model (258 layers, 34.9M parameters at rank 16). Loss only on assistant tokens, hidden states selected before
`lm_head`. Peak 11.3 GB at the 9,000-token cap; a 12,288-token cap thrashed a 16 GB card.

Evaluation: `experiments/bundles/e4b_lora1` is `e4b_v2` plus `adapter: main_lora` (local only: copy `e4b_v2`, add `adapters/main_lora/` from `~/gpu-work/out/RUN/adapter`; weights are never committed).
Local runs mount the bundle's `adapters/` folder (`LOCAL_ADAPTERS_DIR`, `ER_ADAPTERS_DIR`) because the
kernel embeds the submission as text. Result: A65, a regression, with three causes: argument rendering,
thinking mode, and repeated failing commands. Two rules for any next adapter:

- Render training text the way vLLM does (`template_view`: tool-call arguments as dicts) and check the
  rendered call against a base-model call.
- Train in the mode the bundle runs in. With thinking on, the turns need a thought channel; with
  `thinking_budget: 0` they do not.

`lora_train.py train --edit-only` puts loss only on `edit_file`, `write_file` and `submit_patch` turns. It
made things worse (A66): the model edits blind at call 1. Both variants regress E4B, so no adapter ships.
