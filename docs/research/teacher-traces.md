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
