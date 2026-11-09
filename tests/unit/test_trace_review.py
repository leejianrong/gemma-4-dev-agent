import json

from analysis.trace_review import command_category, features, longest_run, summarize


def step(tool, args, status="ok", etype="", t=1.0, tokens=1000):
    body = {"status": status}
    if etype:
        body["error_type"] = etype
    return {
        "source": "agent",
        "tool_calls": [{"function_name": tool, "arguments": args}] if tool else [],
        "observation": {"content": json.dumps(body)} if tool else None,
        "metrics": {"prompt_tokens": tokens},
        "extra": {"elapsed_s": t},
    }


def fabricated():
    return {
        "steps": [
            {"source": "system", "message": "prompt"},
            step("run_command", {"command": "grep -rn foo src"}, t=2.0, tokens=1000),
            step("read_file", {"filepath": "src/a.py"}, t=4.0, tokens=1500),
            step("read_file", {"filepath": "src/a.py"}, status="error", etype="ValueError", t=6.0),
            step("read_file", {"filepath": "tests/test_a.py"}, t=8.0, tokens=2500),
            step(None, {}, t=9.0),
            step("edit_file", {"filepath": "src/a.py"}, status="error", t=11.0),
            step("edit_file", {"filepath": "src/a.py"}, t=13.0),
            step("run_command", {"command": "python -m pytest tests"}, t=20.0),
            step("submit_patch", {}, t=21.0),
        ]
    }


def test_command_category_picks_the_first_matching_class():
    assert command_category("grep -rn x .") == "search"
    assert command_category("python -m pytest -q") == "test"
    assert command_category("python repro.py") == "repro"
    assert command_category("sed -i s/a/b/ f.py") == "shell_edit"
    assert command_category("cat f.py") == "read"
    assert command_category("true") == "other"


def test_features_counts_calls_errors_and_first_edit():
    f = features(fabricated())
    assert f["calls"] == 8 and f["agent_steps"] == 9 and f["text_only_turns"] == 1
    assert f["calls_before_first_edit"] == 4  # grep, 3 reads
    assert f["edit_calls"] == 2 and f["edit_errors"] == 1 and f["read_errors"] == 1
    assert f["repeat_reads"] == 1 and f["distinct_files_read"] == 2
    assert f["reads_test_files"] and f["submit_calls"] == 1 and f["graph_calls"] == 0
    assert f["max_prompt_tokens"] == 2500
    assert f["verified_after_edit"] and f["calls_over_budget"] == 0 and f["long_steps"] == 0


def test_budget_overrun_and_budget_errors_are_counted():
    steps = [step("read_file", {"filepath": "a.py"}) for _ in range(5)]
    steps.append(step("edit_file", {"filepath": "a.py"}, status="error", etype="BudgetExceeded"))
    f = features({"steps": steps}, budget=4)
    assert f["calls_over_budget"] == 2 and f["budget_errors"] == 1


def test_trace_without_edits_counts_every_call_as_before_the_edit():
    t = {"steps": [step("read_file", {"filepath": "a.py"})]}
    f = features(t)
    assert f["edited"] is False and f["calls_before_first_edit"] == 1


def test_summarize_reports_medians_and_shares():
    s = summarize(
        [features(fabricated()), features({"steps": [step("read_file", {"filepath": "a"})]})]
    )
    assert s["traces"] == 2 and s["calls"]["median"] == 4.5
    assert s["share_edited"] == 0.5 and s["total_tools"]["read_file"] == 4


def test_longest_run_finds_repeated_reproduction_scripts():
    assert longest_run([True, False, True, True, True, False]) == 3
    steps = [step("run_command", {"command": "python r.py"}) for _ in range(4)]
    steps.insert(2, step("read_file", {"filepath": "a.py"}))
    f = features({"steps": steps})
    assert f["repro_run"] == 2
    assert summarize([f])["tasks_with_repro_run_4plus"] == 0
