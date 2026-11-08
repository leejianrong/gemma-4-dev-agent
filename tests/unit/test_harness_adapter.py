import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
from analysis import harness_adapter as ha  # noqa: E402
from analysis import runs  # noqa: E402

LIMITS = {"max_tool_calls": 3, "max_time_minutes": 8, "max_turns": 80}


def call(i, name, args, content, issued, done):
    return {
        "step_id": i,
        "source": "agent",
        "message": "thinking",
        "tool_calls": [
            {
                "tool_call_id": f"c{i}",
                "function_name": name,
                "arguments": args,
                "extra": {"elapsed_s": issued},
            }
        ],
        "observation": {"content": json.dumps(content), "extra": {"elapsed_s": done}},
        "metrics": {"prompt_tokens": 1000 * i, "completion_tokens": 50},
    }


ATIF = {
    "schema_version": "ATIF-v1.7",
    "steps": [
        {"step_id": 1, "source": "system", "message": "sys"},
        {"step_id": 2, "source": "user", "message": "issue"},
        call(3, "read_file", {"filepath": "pkg/a.py"}, {"status": "ok", "content": "x"}, 5.0, 5.2),
        call(4, "run_command", {"command": "pytest tests/t.py -k a"}, {"status": "ok"}, 9.0, 12.0),
        call(5, "search_similar_code", {"query": "pkg.a.f"}, {"status": "ok"}, 13.0, 13.1),
        call(
            6,
            "read_file",
            {"filepath": "pkg/b.py"},
            {"status": "error", "error_type": "BudgetExceeded", "error_message": "budget"},
            14.0,
            14.0,
        ),
        {"step_id": 7, "source": "agent", "message": "done", "metrics": {"prompt_tokens": 5000}},
        call(8, "submit_patch", {}, {"status": "ok"}, 16.0, 16.5),
    ],
}
ROW = {
    "run_id": "r1",
    "instance_id": "pkg_1",
    "repo": "o/pkg",
    "resolved": "0",
    "status": "tool_budget",
    "test_exit_code": "1",
    "patch_chars": "0",
    "duration_s": "20.0",
}


def test_every_agent_step_becomes_a_model_step_and_each_tool_call_a_tool_step():
    t = ha.convert(ATIF, ROW, LIMITS)
    kinds = [s["kind"] for s in t["steps"]]
    assert (
        kinds.count("tool") == 5
        and kinds.count("model") == 6
        and [s["i"] for s in t["steps"]] == list(range(len(kinds)))
    )
    first_tool = next(s for s in t["steps"] if s["kind"] == "tool")
    assert first_tool["paths"] == ["pkg/a.py"] and first_tool["ok"] and first_tool["counted"]


def test_free_tools_and_budget_refusals_are_not_counted_and_failures_carry_the_error():
    t = ha.convert(ATIF, ROW, LIMITS)
    tools = [s for s in t["steps"] if s["kind"] == "tool"]
    assert [s["counted"] for s in tools] == [True, True, True, False, False]
    refused = tools[3]
    assert refused["ok"] is False and refused["error"] == "budget"
    assert tools[-1]["tool"] == "submit_patch"


def test_command_paths_and_graph_nodes_are_extracted():
    t = ha.convert(ATIF, ROW, LIMITS)
    tools = {s["tool"]: s for s in t["steps"] if s["kind"] == "tool"}
    assert tools["run_command"]["paths"] == ["tests/t.py"]
    assert tools["search_similar_code"]["nodes"] == ["pkg.a.f"]


def test_model_steps_carry_token_counts_as_context_and_time_never_goes_back():
    t = ha.convert(ATIF, ROW, LIMITS)
    models = [s for s in t["steps"] if s["kind"] == "model"]
    assert [m["context_tokens"] for m in models] == [3000, 4000, 5000, 6000, 5000, 8000]
    times = [s["t_s"] for s in t["steps"]]
    assert times == sorted(times)


def test_the_converted_trace_passes_the_contract_validator():
    assert runs.validate_trace(ha.convert(ATIF, ROW, LIMITS)) == []


def test_outcome_comes_from_the_task_row_including_a_missing_exit_code():
    t = ha.convert(
        ATIF, {**ROW, "test_exit_code": "", "status": "unresolved", "patch_chars": "12"}, LIMITS
    )
    assert t["outcome"]["test_exit_code"] is None and t["outcome"]["patch_chars"] == 12
    assert t["limits"]["max_time_s"] == 480.0


def test_convert_run_writes_one_contract_trace_per_task_with_a_raw_trace(tmp_path):
    (tmp_path / "raw" / "traces").mkdir(parents=True)
    (tmp_path / "raw" / "traces" / "trace_pkg_1.json").write_text(json.dumps(ATIF))
    cols = list(ROW)
    rows = [ROW, {**ROW, "instance_id": "pkg_2"}]
    with open(tmp_path / "task_results.csv", "w", newline="") as fh:
        import csv

        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    out = ha.convert_run(tmp_path, LIMITS)
    assert [p.name for p in out] == ["trace_r1_pkg_1.json"]
    assert runs.validate_trace(json.loads(out[0].read_text())) == []


REAL = Path("data/runs/gemma-4-eval-runner")


@pytest.mark.skipif(not (REAL / "raw" / "traces").is_dir(), reason="smoke-run output not pulled")
def test_real_smoke_run_traces_all_convert_and_validate(tmp_path):
    limits = {"max_tool_calls": 28, "max_time_minutes": 8, "max_turns": 80}
    out = ha.convert_run(REAL, limits, tmp_path)
    assert out and all(runs.validate_trace(json.loads(p.read_text())) == [] for p in out)
