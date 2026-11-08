# Run contract

What the eval runner writes and the dashboards read. Validator: `analysis/runs.py`. Fixtures:
`tests/fixtures/runs/` (synthetic; `make dash` falls back to them when `data/runs/` is empty).

A runs directory holds three things:

| File | One row or file per | Contents |
|---|---|---|
| `runs.csv` | run (a variant at one seed) | variant, parent variant, git sha, model, temperature, seed, subset, limits, counts, rate, wall time, kernel |
| `task_results.csv` | task in a run | status, resolved, exit code, patch size, tool calls, turns, time, tokens, peak context |
| `traces/trace_<run_id>_<instance_id>.json` | task in a run | timestamped steps; schema in `schemas/trace.schema.json` |

`task_results.csv` `tool_calls` is the harness's own count; a trace's `counted` steps are ours and can differ (see `analysis/harness_adapter.py`).

Columns are listed in `RUNS_COLUMNS` and `TASK_COLUMNS` in `analysis/runs.py`.

## Logging a run
`experiments/runs.csv` is the permanent log, one row per run, in the contract's column order:

```
uv run python scripts/log_run.py data/runs/<kernel> --run-id ID --variant NAME --model M \
    --subset 30-task --zip dist/submission.zip
```

Counts, rate and minutes per task are computed from the run's `task_results.csv`. A run without a
zip SHA-256 (`--zip` or `--zip-sha256`) is refused, as is a repeated `run_id`. `make zip` prints
the hash and is byte-deterministic, so the hash names exactly what ran.

## Status
`resolved`, `unresolved` (patch failed the tests), `empty_patch`, `time_limit`, `tool_budget`,
`turn_budget`, `model_timeout`, `error`. `resolved` is true only for `resolved`.

## What the validator enforces beyond the schema
- A trace agrees with itself: step numbers run 0..n, time never goes backwards, a resolved task has
  a non-empty patch, duration covers the last step, counted tool calls stay within the limit
  (`submit_patch` and `get_status` are free), and `tool_budget` means the budget was used up.
- `runs.csv` counts and rate equal what `task_results.csv` holds for that run.
- Every trace matches a `task_results.csv` row with the same status.

## Assumption to check on the first real run
We have not seen the harness's own `task_results.jsonl` or `SessionTrace` (ATIF v1.7). The harness
README names the files but not their fields. This contract is ours; the eval-runner kernel (GEM-8)
carries an adapter from the harness output to it, and the first real run decides which fields the
harness gives us for free (token counts, context size, graph nodes touched). Fields it cannot
supply stay null; the dashboards must cope with null.
