import asyncio
import csv
import dataclasses
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import eval_runner as er
import pytest

ROOT = Path(__file__).resolve().parents[2]


def task(i, repo="a/fastapi"):
    return SimpleNamespace(instance_id=f"{repo.split('/')[1]}_{i}", repo=repo)


TASKS = [task(i) for i in range(6)] + [task(i, "b/rich") for i in range(4)] + [task(1, "c/req")]


def test_stratified_selection_spreads_over_repos_and_is_reproducible():
    got = er.er_select(TASKS, 3, seed=0)
    assert {t.repo for t in got} == {"a/fastapi", "b/rich", "c/req"}
    assert [t.instance_id for t in got] == [t.instance_id for t in er.er_select(TASKS, 3, seed=0)]
    assert len(er.er_select(TASKS, 100)) == len(TASKS)


def test_selection_by_ids_keeps_order_and_rejects_unknown_ids():
    assert [t.instance_id for t in er.er_select(TASKS, ["rich_1", "fastapi_0"])] == [
        "rich_1",
        "fastapi_0",
    ]
    with pytest.raises(ValueError, match="nope"):
        er.er_select(TASKS, ["nope"])
    assert len(er.er_select(TASKS, "all")) == len(TASKS)


def res(**kw):
    base = {
        "resolved": False,
        "agent_patch": "",
        "tool_calls": 3,
        "duration_seconds": 30.0,
        "test_exit_code": -1,
    }
    return SimpleNamespace(**{**base, **kw})


def test_status_covers_resolved_empty_time_budget_unresolved_and_error():
    st = lambda **kw: er.er_status(res(**kw), 28, 480)  # noqa: E731
    assert st(resolved=True, agent_patch="x") == "resolved"
    assert st() == "empty_patch"
    assert st(duration_seconds=479) == "time_limit"
    assert st(tool_calls=28) == "tool_budget"
    assert st(agent_patch="diff") == "unresolved"
    assert st(error="boom") == "error"


def test_row_has_every_contract_column_and_tolerates_missing_harness_fields():
    row = er.er_row("r1", task(0), res(agent_patch=" diff \n"), 28, 480)
    assert (
        list(row) == er.ER_TASK_COLUMNS
        and row["patch_chars"] == 4
        and row["status"] == "unresolved"
    )
    bare = er.er_row("r1", task(0), SimpleNamespace(), 28, 480)
    assert (
        bare["tool_calls"] == "0" and bare["duration_s"] == 0.0 and bare["status"] == "empty_patch"
    )


def test_dump_shows_every_field_cuts_long_strings_and_handles_dataclasses():
    @dataclasses.dataclass
    class R:
        agent_patch: str
        steps: list
        meta: dict

    d = er.er_dump(R("p" * 1000, list(range(30)), {"k": (1, 2)}))
    assert d["_type"] == "R" and d["agent_patch"].startswith("<1000 chars>")
    assert d["steps"][-1] == "<10 more>" and d["meta"] == {"k": [1, 2]}
    assert "agent_patch" in er.er_dump(res())


class FakeEvaluator:
    def __init__(self, fail=(), delay=0.0):
        self.fail, self.delay, self.live, self.peak = set(fail), delay, 0, 0

    async def evaluate_task(self, task, task_index, total_tasks):
        self.live += 1
        self.peak = max(self.peak, self.live)
        await asyncio.sleep(self.delay)
        self.live -= 1
        if task.instance_id in self.fail:
            raise RuntimeError("sandbox died")
        return res(resolved=task_index % 2 == 0, agent_patch="d")


P = {"run_id": "r1", "concurrency": 2, "max_minutes": 5, "max_tool_calls": 28, "max_time_s": 480}


def run(tmp_path, ev, tasks, deadline=None, p=None):
    state = {"done": 0, "inflight": 0, "total": len(tasks), "skipped": []}
    dl = deadline if deadline is not None else time.time() + 60
    rows = asyncio.run(er.er_run_all(ev, tasks, tmp_path, p or P, dl, state))
    return rows, state


def test_run_writes_a_row_and_a_raw_dump_per_task_and_bounds_concurrency(tmp_path):
    ev = FakeEvaluator(delay=0.02)
    rows, state = run(tmp_path, ev, TASKS[:5])
    assert len(rows) == 5 and state["done"] == 5 and ev.peak == 2
    lines = (tmp_path / "raw_results.jsonl").read_text().splitlines()
    assert len(lines) == 5 and json.loads(lines[0])["_type"] == "SimpleNamespace"
    on_disk = list(csv.DictReader(open(tmp_path / "task_results.csv")))
    assert len(on_disk) == 5 and list(on_disk[0]) == er.ER_TASK_COLUMNS


def test_one_failing_task_becomes_an_error_row_and_the_rest_still_run(tmp_path):
    rows, _ = run(tmp_path, FakeEvaluator(fail={"fastapi_1"}), TASKS[:3])
    by = {r["instance_id"]: r for r in rows}
    assert by["fastapi_1"]["status"] == "error" and by["fastapi_0"]["status"] != "error"
    assert len(rows) == 3


def test_tasks_past_the_deadline_are_skipped_and_reported(tmp_path):
    rows, state = run(tmp_path, FakeEvaluator(), TASKS[:3], deadline=time.time() - 1)
    assert rows == [] and state["skipped"] == [t.instance_id for t in TASKS[:3]]


def test_summary_counts_status_and_repos():
    rows = [
        er.er_row("r1", task(0), res(resolved=True, agent_patch="d"), 28, 480),
        er.er_row("r1", task(1), res(), 28, 480),
        er.er_row("r1", task(0, "b/rich"), res(agent_patch="d"), 28, 480),
    ]
    s = er.er_summary(rows, {**P, "model": "m", "sandbox": "subprocess", "zip_sha256": "z"}, {})
    assert s["resolved"] == 1 and s["resolution_rate"] == round(1 / 3, 4)
    assert s["by_status"] == {"resolved": 1, "empty_patch": 1, "unresolved": 1}
    assert s["by_repo"]["a/fastapi"] == {"resolved": 1, "tasks": 2}


def test_wheel_names_get_their_cuda_suffix_back(tmp_path):
    wh = tmp_path / "wh"
    wh.mkdir()
    (wh / "torch-2.9.0cu128-cp312-linux.whl").write_bytes(b"x")
    (wh / "other-1.0-py3-none-any.whl").write_bytes(b"x")
    (wh / "nvidia_cutlass-1.0-py3-none-any.whl").write_bytes(b"x")
    names = [Path(w).name for w in er.er_prepare_wheels(wh, tmp_path / "tmp")]
    assert names == ["other-1.0-py3-none-any.whl", "torch-2.9.0+cu128-cp312-linux.whl"]


def test_submission_model_rewrite_drops_adapters_and_sub_agent_adapter_lines(tmp_path):
    files = {
        "agent.yaml": "name: a\nmodel: old\nadapter: main_lora\n",
        "sub_agents/s.yaml": "model: old\nadapter: tool_lora\n",
        "adapters/main_lora/adapter_config.json": "{}",
    }
    root, model = er.er_write_submission(tmp_path / "s", files, "new")
    assert model == "new" and "model: new" in (root / "agent.yaml").read_text()
    assert "adapter" not in (root / "sub_agents" / "s.yaml").read_text()
    assert not (root / "adapters").exists()
    _, same = er.er_write_submission(tmp_path / "t", files, "")
    assert same == "old"


def test_eval_limits_read_the_submission_config_with_harness_defaults(tmp_path):
    pytest.importorskip("yaml")
    (tmp_path / "eval_config.yaml").write_text(
        "evaluation:\n  max_tool_calls: 28\n  max_time_minutes: 8\n  max_turns: 80\n"
    )
    got = er.er_eval_limits(tmp_path)
    assert got["max_tool_calls"] == 28 and got["max_turns"] == 80 and got["timeout_seconds"] == 300
    assert er.er_eval_limits(tmp_path / "none")["max_tool_calls"] == 100


def test_build_embeds_parameters_the_zip_hash_and_gpu_metadata(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    sys.path.insert(0, str(ROOT / "kaggle"))
    import build_kernel as bk

    monkeypatch.setenv("EVAL_TASKS", "7")
    monkeypatch.setenv("EVAL_CONCURRENCY", "2")
    p = bk.eval_params(bk.submission_files())
    assert p["tasks"] == 7 and p["concurrency"] == 2 and len(p["zip_sha256"]) == 64
    assert p["model"].startswith("gemma-4-")
    monkeypatch.setenv("EVAL_TASKS", "a_1,b_2")
    assert bk.eval_params(bk.submission_files())["tasks"] == ["a_1", "b_2"]


def test_wheel_python_mismatch_names_the_tag_the_wheels_target():
    wheels = [
        "/w/vllm-0.19-cp38-abi3-x.whl",
        "/w/numpy-2-cp312-cp312-linux.whl",
        "/w/a-1-py3-none-any.whl",
    ]
    assert er.er_wheel_python_mismatch(wheels, (3, 12)) == ""
    assert er.er_wheel_python_mismatch(wheels, (3, 13)) == "cp312"
    assert er.er_wheel_python_mismatch(["/w/a-1-py3-none-any.whl"], (3, 13)) == ""


def test_trace_metrics_give_token_totals_and_peak_context(tmp_path):
    trace = {
        "final_metrics": {"total_prompt_tokens": 1000, "total_completion_tokens": 50},
        "steps": [
            {"source": "system"},
            {"source": "agent", "metrics": {"prompt_tokens": 300}},
            {"source": "agent", "metrics": {"prompt_tokens": 700}},
        ],
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(trace))
    assert er.er_trace_metrics(p) == {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "max_context_tokens": 700,
    }
    assert er.er_trace_metrics(tmp_path / "missing.json") == {}
    row = er.er_row("r", task(0), res(trace_path=str(p), total_llm_calls=9), 28, 480)
    assert row["prompt_tokens"] == 1000 and row["max_context_tokens"] == 700 and row["turns"] == 9


def test_full_patch_and_test_output_are_saved_per_task(tmp_path):
    er.er_save_artifacts(tmp_path, res(agent_patch="diff --git", test_output="E boom"), "t_1")
    assert (tmp_path / "patches" / "t_1.patch").read_text() == "diff --git"
    assert (tmp_path / "test_outputs" / "t_1.log").read_text() == "E boom"
    er.er_save_artifacts(tmp_path, res(), "t_2")
    assert not (tmp_path / "patches" / "t_2.patch").exists()


def test_a_harness_error_message_makes_the_status_error():
    assert er.er_status(res(error_message="sandbox died"), 28, 480) == "error"


def _runner_paths(monkeypatch, **env):
    import importlib

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    mod = importlib.reload(er)
    return mod.ER_WHEELHOUSE, mod.ER_MODEL_ROOT


def test_wheelhouse_and_model_paths_default_to_kaggle_mounts_and_can_be_moved(monkeypatch):
    for k in ("ER_WHEELHOUSE_DIR", "ER_MODEL_ROOT_DIR"):
        monkeypatch.delenv(k, raising=False)
    wheels, models = _runner_paths(monkeypatch)
    assert str(wheels).startswith("/kaggle/input/datasets/metric/")
    assert str(models) == "/kaggle/input/models/google/gemma-4/other"
    wheels, models = _runner_paths(
        monkeypatch, ER_WHEELHOUSE_DIR="/srv/wh", ER_MODEL_ROOT_DIR="/srv/models"
    )
    assert (str(wheels), str(models)) == ("/srv/wh", "/srv/models")
    monkeypatch.delenv("ER_WHEELHOUSE_DIR")
    monkeypatch.delenv("ER_MODEL_ROOT_DIR")
    assert str(_runner_paths(monkeypatch)[1]).startswith("/kaggle/")  # leave the module as found
