import copy
import csv
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
from analysis import runs  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "runs"


def load(name):
    return json.loads((FIX / "traces" / name).read_text())


def solved():
    return load("trace_fx_baseline_fastapi_0001.json")


def test_fixture_directory_is_valid_and_covers_solved_timed_out_and_empty():
    assert runs.validate_dir(FIX) == []
    statuses = {
        json.loads(p.read_text())["outcome"]["status"] for p in (FIX / "traces").glob("*.json")
    }
    assert {"resolved", "time_limit", "empty_patch"} <= statuses


def test_a_trace_missing_a_required_field_is_rejected():
    t = solved()
    del t["limits"]
    assert any("limits" in p for p in runs.validate_trace(t))


def test_a_bad_status_or_negative_time_is_rejected():
    t = solved()
    t["outcome"]["status"] = "great"
    assert runs.validate_trace(t)
    t = solved()
    t["steps"][1]["t_s"] = -1
    assert any("steps/1/t_s" in p for p in runs.validate_trace(t))


def test_resolved_must_agree_with_status_and_a_patch():
    t = solved()
    t["outcome"]["resolved"] = False
    assert any("resolved=False" in p for p in runs.validate_trace(t))
    t = solved()
    t["outcome"]["patch_chars"] = 0
    assert any("empty patch" in p for p in runs.validate_trace(t))


def test_steps_must_be_numbered_and_not_go_back_in_time():
    t = solved()
    t["steps"][2]["t_s"] = 0.5
    assert any("back in time" in p for p in runs.validate_trace(t))
    t = solved()
    t["steps"][3]["i"] = 9
    assert any("expected 3" in p for p in runs.validate_trace(t))


def test_budget_checks_use_counted_calls_only():
    t = solved()
    t["limits"]["max_tool_calls"] = 3
    assert any(
        "exceed" in p for p in runs.validate_trace(t)
    )  # 4 counted calls; submit_patch is free
    t = copy.deepcopy(solved())
    t["outcome"].update(status="tool_budget", resolved=False)
    assert any("not used up" in p for p in runs.validate_trace(t))


def copy_fixture(tmp_path):
    dest = tmp_path / "runs"
    shutil.copytree(FIX, dest)
    return dest


def rewrite(path, edit):
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    edit(rows)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_runs_csv_must_agree_with_task_results(tmp_path):
    d = copy_fixture(tmp_path)
    rewrite(d / "runs.csv", lambda rows: rows[0].update(n_resolved="3"))
    assert any("n_resolved=3" in p for p in runs.validate_dir(d))


def test_task_results_reject_duplicates_and_disagreeing_status(tmp_path):
    d = copy_fixture(tmp_path)

    def edit(rows):
        rows[1]["status"] = "resolved"
        rows.append(dict(rows[0]))

    rewrite(d / "task_results.csv", edit)
    got = runs.validate_task_results(d / "task_results.csv")
    assert any("duplicate" in p for p in got) and any("disagree" in p for p in got)


def test_a_trace_that_contradicts_task_results_is_reported(tmp_path):
    d = copy_fixture(tmp_path)
    rewrite(d / "task_results.csv", lambda rows: rows[2].update(status="unresolved"))
    assert any("status differs" in p for p in runs.validate_dir(d))


def test_missing_columns_are_named(tmp_path):
    p = tmp_path / "runs.csv"
    p.write_text("run_id,variant\nx,y\n")
    assert "missing columns" in runs.validate_runs(p)[0]
