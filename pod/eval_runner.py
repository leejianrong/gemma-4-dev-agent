"""Kaggle GPU eval runner: unpack our submission, serve the model with vLLM, run Phase 1 and 2.

Ports the official getting-started notebook (wheelhouse install, VllmServer, Evaluator) and adds
what a paid, hour-long run needs: stage markers, a heartbeat, a time cap, per-task rows written as
each task finishes (a crash loses nothing), a raw dump of every field the harness's result object
has (the harness's own schema is unseen, A30), and a copy of the harness results directory.

EVAL_PARAMS and SUBMISSION_FILES are injected by kaggle/build_kernel.py (kind "eval"). The harness
packages (swegemma, adk_submission, google.adk, torch) exist only on Kaggle, so they are imported
inside functions and everything else here is testable without them.
Outputs (OUT_DIR): task_results.csv, raw_results.jsonl, summary.json, report.json, raw/ (harness
results dir), our_submission/.
"""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import glob
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# Kaggle mounts these read-only; a pod downloads them elsewhere and sets the two env vars.
ER_WHEELHOUSE = Path(
    os.environ.get(
        "ER_WHEELHOUSE_DIR", "/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse"
    )
)
ER_MODEL_ROOT = Path(
    os.environ.get("ER_MODEL_ROOT_DIR", "/kaggle/input/models/google/gemma-4/other")
)
ER_ENV = {
    "TRANSFORMERS_NO_TF": "1",
    "TRANSFORMERS_NO_FLAX": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "VLLM_NO_USAGE_STATS": "1",
    "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
    "VLLM_ENGINE_READY_TIMEOUT_S": "1200",
    "VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS": "1",
    "NCCL_DEBUG": "WARN",
    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    "LITELLM_TELEMETRY": "False",
    "LITELLM_LOG": "WARNING",
    "OPENAI_API_KEY": "EMPTY",
    "LOCAL_API_KEY": "EMPTY",
    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    "OTEL_SDK_DISABLED": "true",
    "OTEL_PYTHON_DISABLED": "true",
}
ER_TASK_COLUMNS = (
    "run_id instance_id repo resolved status test_exit_code patch_chars tool_calls turns "
    "duration_s prompt_tokens completion_tokens max_context_tokens"
).split()
# Attribute names the harness result might use for a field; the first one present wins. The raw dump
# (raw_results.jsonl) shows what really exists, and these lists are then tightened.
ER_FIELDS = {
    "test_exit_code": ("test_exit_code", "exit_code"),
    "tool_calls": ("tool_calls", "num_tool_calls", "tool_call_count"),
    "turns": ("turns", "total_llm_calls", "num_turns", "llm_calls"),
    "duration_s": ("duration_seconds", "duration_s", "duration"),
    "prompt_tokens": ("prompt_tokens", "input_tokens"),
    "completion_tokens": ("completion_tokens", "output_tokens"),
    "max_context_tokens": ("max_context_tokens", "peak_context_tokens"),
}


def er_log(msg: str) -> None:
    print(msg, flush=True)


def er_pick(obj, names, default=""):
    for n in names:
        v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
        if v is not None:
            return v
    return default


def er_select(tasks: list, spec, seed: int = 0) -> list:
    """`spec` is a list of instance ids, an int N (stratified round-robin over repos), or 'all'."""
    if spec == "all":
        return list(tasks)
    if isinstance(spec, list):
        by_id = {t.instance_id: t for t in tasks}
        missing = [i for i in spec if i not in by_id]
        if missing:
            raise ValueError(f"unknown task ids: {missing}")
        return [by_id[i] for i in spec]
    import random

    rng = random.Random(seed)
    by_repo: dict[str, list] = {}
    for t in tasks:
        by_repo.setdefault(t.repo, []).append(t)
    for v in by_repo.values():
        v.sort(key=lambda t: t.instance_id)
        rng.shuffle(v)
    order = sorted(by_repo, key=lambda r: (-len(by_repo[r]), r))
    out: list = []
    while len(out) < int(spec) and any(by_repo.values()):
        for r in order:
            if by_repo[r] and len(out) < int(spec):
                out.append(by_repo[r].pop())
    return out


def er_status(result, max_tool_calls: int, max_time_s: float) -> str:
    """Our status from a harness result. Heuristic until the real status fields are known."""
    if er_pick(result, ("error", "error_message", "exception"), None):
        return "error"
    if bool(er_pick(result, ("resolved",), False)):
        return "resolved"
    if not str(er_pick(result, ("agent_patch", "patch"), "") or "").strip():
        calls = int(er_pick(result, ER_FIELDS["tool_calls"], 0) or 0)
        dur = float(er_pick(result, ER_FIELDS["duration_s"], 0) or 0)
        if dur >= max_time_s - 5:
            return "time_limit"
        if calls >= max_tool_calls:
            return "tool_budget"
        return "empty_patch"
    return "unresolved"


def er_row(run_id: str, task, result, max_tool_calls: int, max_time_s: float) -> dict:
    patch = str(er_pick(result, ("agent_patch", "patch"), "") or "")
    status = er_status(result, max_tool_calls, max_time_s)
    row = {
        "run_id": run_id,
        "instance_id": task.instance_id,
        "repo": task.repo,
        "resolved": int(status == "resolved"),
        "status": status,
        "patch_chars": len(patch.strip()),
    }
    for col, names in ER_FIELDS.items():
        v = er_pick(result, names, "")
        row[col] = v if v != "" else ("0" if col in ("tool_calls", "turns") else "")
    if row["duration_s"] == "":
        row["duration_s"] = 0.0
    for col, v in er_trace_metrics(er_pick(result, ("trace_path",), "")).items():
        row[col] = v
    return {c: row[c] for c in ER_TASK_COLUMNS}


def er_error_row(run_id: str, task, exc: BaseException, elapsed: float) -> dict:
    row = dict.fromkeys(ER_TASK_COLUMNS, "")
    row.update(
        run_id=run_id,
        instance_id=task.instance_id,
        repo=task.repo,
        resolved=0,
        status="error",
        patch_chars=0,
        tool_calls=0,
        turns=0,
        duration_s=round(elapsed, 1),
    )
    return row


def er_trace_metrics(trace_path) -> dict:
    """Token totals and peak per-call prompt size from an ATIF trace; {} when unreadable.

    The result object's own total_tokens is 0; the trace holds the real counts (smoke run, A30).
    """
    try:
        t = json.loads(Path(trace_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    fm = t.get("final_metrics") or {}
    peaks = [
        (s.get("metrics") or {}).get("prompt_tokens") or 0
        for s in t.get("steps", [])
        if s.get("source") == "agent"
    ]
    return {
        "prompt_tokens": fm.get("total_prompt_tokens", ""),
        "completion_tokens": fm.get("total_completion_tokens", ""),
        "max_context_tokens": max(peaks) if peaks else "",
    }


def er_save_artifacts(out: Path, result, instance_id: str) -> None:
    """Full patch and verification output per task (the raw dump cuts long strings)."""
    for sub, attr, ext in (
        ("patches", "agent_patch", "patch"),
        ("test_outputs", "test_output", "log"),
    ):
        text = er_pick(result, (attr,), "")
        if text:
            d = out / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{instance_id}.{ext}").write_text(str(text), encoding="utf-8")


def er_dump(result, limit: int = 300) -> dict:
    """Every field of a harness result, JSON-safe, long strings cut: shows the real schema."""
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        raw = dataclasses.asdict(result)
    elif hasattr(result, "model_dump"):
        raw = result.model_dump()
    elif isinstance(result, dict):
        raw = dict(result)
    else:
        raw = dict(vars(result))

    def safe(v, depth=0):
        if isinstance(v, str):
            return v if len(v) <= limit else f"<{len(v)} chars> {v[:limit]}"
        if isinstance(v, (int, float, bool)) or v is None:
            return v
        if isinstance(v, dict) and depth < 3:
            return {str(k): safe(x, depth + 1) for k, x in list(v.items())[:40]}
        if isinstance(v, (list, tuple)) and depth < 3:
            return [safe(x, depth + 1) for x in list(v)[:20]] + (
                [f"<{len(v) - 20} more>"] if len(v) > 20 else []
            )
        return f"<{type(v).__name__}> {str(v)[:limit]}"

    return {"_type": type(result).__name__, **{str(k): safe(v) for k, v in raw.items()}}


def er_append_csv(path: Path, row: dict) -> None:
    new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ER_TASK_COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


async def er_run_all(
    evaluator, tasks, out: Path, p: dict, deadline: float, state: dict
) -> list[dict]:
    """Run tasks with bounded concurrency; write one row and one raw dump per finished task."""
    sem = asyncio.Semaphore(max(1, int(p["concurrency"])))
    rows: list[dict] = []
    lock = asyncio.Lock()
    n = len(tasks)

    async def one(i: int, task) -> None:
        async with sem:
            if time.time() > deadline:
                state["skipped"].append(task.instance_id)
                er_log(f"SKIP {task.instance_id}: past the {p['max_minutes']} minute cap")
                return
            state["inflight"] += 1
            t0 = time.time()
            try:
                res = await evaluator.evaluate_task(task=task, task_index=i, total_tasks=n)
                row = er_row(p["run_id"], task, res, p["max_tool_calls"], p["max_time_s"])
                raw = er_dump(res)
                er_save_artifacts(out, res, task.instance_id)
            except Exception as e:  # one bad task must not lose the rest
                er_log(f"ERROR {task.instance_id}: {type(e).__name__}: {e}")
                row, raw = er_error_row(p["run_id"], task, e, time.time() - t0), {"error": repr(e)}
            finally:
                state["inflight"] -= 1
            async with lock:
                rows.append(row)
                er_append_csv(out / "task_results.csv", row)
                with open(out / "raw_results.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"instance_id": task.instance_id, **raw}) + "\n")
                state["done"] += 1
            er_log(
                f"TASK {state['done']}/{n} {task.instance_id} status={row['status']} "
                f"calls={row['tool_calls']} t={row['duration_s']}s"
            )

    await asyncio.gather(*(one(i, t) for i, t in enumerate(tasks, 1)))
    return rows


def er_summary(rows: list[dict], p: dict, extra: dict) -> dict:
    n = len(rows)
    resolved = sum(int(r["resolved"]) for r in rows)
    by_status: dict[str, int] = {}
    by_repo: dict[str, list[int]] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_repo.setdefault(r["repo"], []).append(int(r["resolved"]))
    return {
        "run_id": p["run_id"],
        "tasks": n,
        "resolved": resolved,
        "resolution_rate": round(resolved / n, 4) if n else 0.0,
        "by_status": by_status,
        "by_repo": {k: {"resolved": sum(v), "tasks": len(v)} for k, v in sorted(by_repo.items())},
        "zip_sha256": p.get("zip_sha256", ""),
        "model": p["model"],
        "sandbox": p["sandbox"],
        **extra,
    }


def er_set_env() -> None:
    for k, v in ER_ENV.items():
        os.environ.setdefault(k, v)


def er_prepare_wheels(wheelhouse: Path, tmp: Path) -> list[str]:
    """Kaggle dataset uploads strip "+cu128" from wheel names; restore them."""
    for pat in (
        "/usr/local/lib/python*/dist-packages/*cutlass*.pth",
        "/usr/local/lib/python*/site-packages/*cutlass*.pth",
    ):
        for pth in glob.glob(pat):
            try:
                os.unlink(pth)
            except OSError:
                pass
    tmp.mkdir(parents=True, exist_ok=True)
    for w in wheelhouse.glob("*.whl"):
        if "cutlass" in w.name.lower():
            continue
        name = (
            w.name.replace("cu128", "+cu128") if "cu128" in w.name and "+" not in w.name else w.name
        )
        target = tmp / name
        if not target.exists():
            try:
                os.symlink(w, target)
            except OSError:
                shutil.copyfile(w, target)
    return sorted(str(w) for w in tmp.glob("*.whl"))


def er_wheel_python_mismatch(wheels: list[str], version: tuple[int, int]) -> str:
    """The cpXY tag the wheels target when it differs from this interpreter, else ''."""
    want = f"cp{version[0]}{version[1]}"
    tags = {m.group(1) for w in wheels if (m := re.search(r"-(cp3\d+)-cp3\d+-", Path(w).name))}
    return "" if not tags or want in tags else "/".join(sorted(tags))


def er_gpu_line() -> str:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return " | ".join(out.stdout.strip().splitlines()) or out.stderr.strip()[:200]
    except Exception as e:
        return f"nvidia-smi failed: {e}"


def er_heartbeat(state: dict, t0: float, stop: threading.Event, every: int = 60) -> None:
    while not stop.wait(every):
        er_log(
            f"HEARTBEAT t+{time.time() - t0:.0f}s done={state['done']}/{state['total']} "
            f"inflight={state['inflight']} gpu: {er_gpu_line()}"
        )


def er_write_submission(root: Path, files: dict[str, str], model: str) -> tuple[Path, str]:
    """Write the embedded submission; rewrite the model if asked and drop 31B-shaped adapters."""
    shutil.rmtree(root, ignore_errors=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    declared = re.search(r"^\s*model:\s*(\S+)", files["agent.yaml"], re.MULTILINE)
    declared_model = declared.group(1) if declared else ""
    if model and model != declared_model:
        for y in [root / "agent.yaml", *sorted((root / "sub_agents").glob("*.yaml"))]:
            if y.is_file():
                t = re.sub(
                    r"^(\s*model:\s*).*$", rf"\g<1>{model}", y.read_text(), flags=re.MULTILINE
                )
                y.write_text(re.sub(r"^\s*adapter:\s*.*\n?", "", t, flags=re.MULTILINE))
        shutil.rmtree(root / "adapters", ignore_errors=True)
    return root, model or declared_model


def er_eval_limits(root: Path) -> dict:
    import yaml

    f = root / "eval_config.yaml"
    raw = (yaml.safe_load(f.read_text()) or {}) if f.is_file() else {}
    s = raw.get("evaluation", raw)
    turns = s.get("max_turns", s.get("max_llm_calls"))
    return {
        "timeout_seconds": int(s.get("timeout_seconds", 300)),
        "verification_timeout_seconds": int(s.get("verification_timeout_seconds", 300)),
        "max_tool_calls": int(s.get("max_tool_calls", 100)),
        "max_time_minutes": float(s.get("max_time_minutes", 60.0)),
        "max_turns": int(turns) if turns is not None else None,
    }


def er_tp(gpus: int, override: int = 0) -> int:
    """Tensor-parallel size: all of 1, 2 or 4 GPUs unless overridden (a small model may need 1)."""
    return override or (4 if gpus >= 4 else (2 if gpus >= 2 else 1))


def er_dtype(major: int, bf16: bool, override: str | None) -> str:
    """vLLM dtype. ER_VLLM_DTYPE overrides it (a Colab T4 has no bf16 and needs "half"); otherwise
    the competition's L4s (compute 8.x) run bfloat16 and anything older is refused."""
    if override:
        return override
    if major < 8:
        raise SystemExit(
            f"ERROR GPU compute capability {major}.x cannot run bfloat16 (competition: 4 x L4): "
            "request the NvidiaL4 machine shape, or set ER_VLLM_DTYPE=half for an experiment"
        )
    return "bfloat16" if bf16 else "auto"


def er_main_impl(p: dict, files: dict[str, str], data: Path, outd: Path) -> dict:
    """The whole run. Returns the report; raises on a failure that should fail the kernel."""
    t0 = time.time()
    er_set_env()
    outd.mkdir(parents=True, exist_ok=True)
    state = {"done": 0, "inflight": 0, "total": 0, "skipped": []}
    er_log(f"STAGE gpu-check (t+0s) python={sys.version.split()[0]} {er_gpu_line()}")
    if p.get("probe"):  # report the hardware and stop: a cheap way to test accelerator names
        summary = {"probe": True, "python": sys.version.split()[0], "gpu": er_gpu_line()}
        (outd / "report.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary
    if not ER_WHEELHOUSE.is_dir():
        raise SystemExit(f"ERROR wheelhouse dataset missing at {ER_WHEELHOUSE}")
    er_log("STAGE install-wheels")
    wheels = er_prepare_wheels(ER_WHEELHOUSE, Path("/tmp/wheelhouse"))
    if not wheels:
        raise SystemExit("ERROR no wheels found in the wheelhouse")
    bad = er_wheel_python_mismatch(wheels, sys.version_info[:2])
    if bad:
        raise SystemExit(
            f"ERROR wheels target {bad} but this kernel runs Python "
            f"{sys.version_info[0]}.{sys.version_info[1]}; pin the original Docker image"
        )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--force-reinstall", *wheels],
        check=True,
    )
    importlib.invalidate_caches()

    import litellm
    import torch
    from adk_submission import (
        VllmConfig,
        VllmServer,
        discover_adapters,
        validate_directory,
    )
    from adk_submission.discovery import discover_declared_models
    from google.adk.agents.context_cache_config import ContextCacheConfig
    from google.adk.apps._configs import EventsCompactionConfig
    from swegemma.config import (
        ALLOWED_ADAPTER_EXTENSIONS,
        EvalConfig,
        build_submission_limits,
    )
    from swegemma.evaluate import Evaluator
    from swegemma.models import load_tasks

    litellm.drop_params = True
    er_log(f"STAGE prepare-submission (t+{time.time() - t0:.0f}s)")
    agent_dir, model = er_write_submission(outd / "our_submission", files, p["model"])
    p = {**p, "model": model}
    declared = discover_declared_models(agent_dir)
    if len(declared) != 1 or model not in declared:
        raise SystemExit(f"ERROR expected exactly the model {model}, got {sorted(declared)}")
    limits_cfg = er_eval_limits(agent_dir)
    p["max_tool_calls"] = limits_cfg["max_tool_calls"]
    p["max_time_s"] = limits_cfg["max_time_minutes"] * 60
    limits, gen_constraints = build_submission_limits()
    validate_directory(
        agent_dir, limits=limits
    )  # the official validator; raises on a bad submission
    er_log("official validate_directory: ok")

    model_path = ER_MODEL_ROOT / model / "2"
    if not model_path.exists():
        raise SystemExit(
            f"ERROR model weights missing at {model_path}; attach the google/gemma-4 model"
        )
    all_tasks = load_tasks(data / "tasks.jsonl")
    tasks = er_select(all_tasks, p["tasks"], p["seed"])
    state["total"] = len(tasks)
    er_log(f"selected {len(tasks)} tasks: {[t.instance_id for t in tasks]}")

    adapters = discover_adapters(str(agent_dir), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
    adapter_map = getattr(adapters, "adapters", None) or {}
    ranks = [r for i in adapter_map.values() if (r := getattr(i, "rank", None)) and r > 0]
    gpus = torch.cuda.device_count() if torch.cuda.is_available() else 1
    if gpus < 1 or not torch.cuda.is_available():
        raise SystemExit("ERROR no CUDA device visible")
    tp = er_tp(gpus, p.get("tensor_parallel", 0))
    dtype = er_dtype(
        torch.cuda.get_device_capability(0)[0],
        torch.cuda.is_bf16_supported(),
        os.environ.get("ER_VLLM_DTYPE"),
    )
    er_log(f"STAGE start-vllm (t+{time.time() - t0:.0f}s) gpus={gpus} tp={tp} model={model}")
    extra = (
        ("--hf-overrides", '{"architectures": ["Gemma4ForCausalLM"], "model_type": "gemma4"}')
        if model == "gemma-4-12b-it-qat-w4a16-ct"
        else ()
    )
    cfg = VllmConfig(
        model=str(model_path),
        port=8000,
        host="127.0.0.1",
        tool_call_parser="gemma4",
        reasoning_parser="gemma4",
        max_model_len=32768,
        dtype=dtype,
        gpu_memory_utilization=0.90,
        enable_auto_tool_choice=True,
        enable_lora=bool(adapter_map),
        max_loras=max(1, len(adapter_map)),
        max_lora_rank=max(ranks) if ranks else 128,
        scheduler_reserve_full_isl=False,
        tensor_parallel_size=tp,
        startup_timeout=60 * 20,
        extra_args=extra,
    )
    server = VllmServer(cfg, adapter_manifest=adapters)
    stop = threading.Event()
    threading.Thread(target=er_heartbeat, args=(state, t0, stop), daemon=True).start()
    try:
        server.start()
        er_log(f"vLLM up after {time.time() - t0:.0f}s at {server.base_url}")
        models = server.create_model_registry(
            aliases=[model], model_prefix="openai/", api_key=os.environ["LOCAL_API_KEY"]
        )
        results_dir = outd / "raw"
        cfg_eval = EvalConfig(
            tasks_path=data / "tasks.jsonl",
            snapshots_dir=data / "snapshots",
            results_dir=results_dir,
            submission_dir=agent_dir,
            models=models,
            sandbox=p["sandbox"],
            timeout_seconds=limits_cfg["timeout_seconds"],
            verification_timeout_seconds=limits_cfg["verification_timeout_seconds"],
            max_time_minutes=limits_cfg["max_time_minutes"],
            max_tool_calls=limits_cfg["max_tool_calls"],
            max_turns=limits_cfg["max_turns"],
            limits=limits,
            generation_constraints=gen_constraints,
            adapter_manifest=adapters,
            context_cache_config=ContextCacheConfig(
                min_tokens=2048, ttl_seconds=1800, cache_intervals=10
            ),
            events_compaction_config=EventsCompactionConfig(
                compaction_interval=15,
                overlap_size=2,
                token_threshold=14336,
                event_retention_size=5,
            ),
            graph_dir=str(data / "graphs"),
            embeddings_dir=str(data / "embeddings"),
            wheels_dir=data / "wheels",
            verbose=False,
        )
        er_log(
            f"STAGE evaluate (t+{time.time() - t0:.0f}s) sandbox={p['sandbox']} limits={limits_cfg}"
        )
        deadline = t0 + p["max_minutes"] * 60
        rows = asyncio.run(er_run_all(Evaluator(cfg_eval), tasks, outd, p, deadline, state))
    finally:
        stop.set()
        try:
            server.stop()
        except Exception as e:
            er_log(f"WARN vLLM stop failed: {e}")
    summary = er_summary(
        rows,
        p,
        {
            "skipped": state["skipped"],
            "limits": limits_cfg,
            "wall_s": round(time.time() - t0, 1),
            "validate_directory": "ok",
        },
    )
    (outd / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (outd / "report.json").write_text(json.dumps(summary, separators=(",", ":")), encoding="utf-8")
    return summary


def er_main() -> int:
    """Kernel entry; DATA, OUTD, EVAL_PARAMS and SUBMISSION_FILES come from the kernel wrapper."""
    summary = er_main_impl(EVAL_PARAMS, SUBMISSION_FILES, DATA, OUTD)  # noqa: F821
    er_log(json.dumps(summary, indent=1))
    return 0
