import csv
import shutil
from pathlib import Path

import log_run
import pytest

pytest.importorskip("jsonschema")
from analysis import runs  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "runs"


def argv(tmp_path, *extra, run_id="fx_baseline"):
    d = tmp_path / "run"
    if not d.exists():
        shutil.copytree(FIX, d)
    zip_path = tmp_path / "s.zip"
    zip_path.write_bytes(b"zip")
    base = [
        "log_run.py",
        str(d),
        "--run-id",
        run_id,
        "--variant",
        "baseline",
        "--model",
        "gemma-4-31b-it-qat-w4a16-ct",
        "--subset",
        "fixture-3",
        "--log",
        str(tmp_path / "runs.csv"),
    ]
    return base + list(extra or ["--zip", str(zip_path)])


def test_a_row_without_a_zip_hash_is_rejected_and_nothing_is_written(tmp_path, capsys):
    assert log_run.main(argv(tmp_path, "--seed", "0")) == 1
    assert "needs the submission zip" in capsys.readouterr().err
    assert not (tmp_path / "runs.csv").exists()


def test_a_malformed_hash_is_rejected(tmp_path):
    assert log_run.main(argv(tmp_path, "--zip-sha256", "abc")) == 1


def test_columns_are_written_in_the_contract_order_and_counts_come_from_task_results(tmp_path):
    assert log_run.main(argv(tmp_path)) == 0
    with open(tmp_path / "runs.csv", newline="") as fh:
        rd = csv.DictReader(fh)
        assert rd.fieldnames == runs.RUNS_COLUMNS
        (row,) = list(rd)
    assert (row["n_tasks"], row["n_resolved"], row["n_time_limit"], row["n_empty_patch"]) == (
        "3",
        "1",
        "1",
        "1",
    )
    assert float(row["minutes_per_task"]) == round(float(row["wall_s"]) / 60 / 3, 2)
    assert len(row["zip_sha256"]) == 64


def test_a_repeated_run_id_and_an_unknown_run_are_refused(tmp_path, capsys):
    assert log_run.main(argv(tmp_path)) == 0
    assert log_run.main(argv(tmp_path)) == 1
    assert "already in" in capsys.readouterr().err
    assert log_run.main(argv(tmp_path, run_id="nope")) == 1


def test_the_logged_file_passes_the_contract_validator(tmp_path):
    log_run.main(argv(tmp_path))
    assert runs.validate_runs(tmp_path / "runs.csv", tmp_path / "run" / "task_results.csv") == []


def test_a_log_with_other_columns_is_not_appended_to(tmp_path):
    (tmp_path / "runs.csv").write_text("run_id,variant\nold,x\n")
    assert log_run.main(argv(tmp_path)) == 1


def test_contract_validator_rejects_a_missing_or_short_hash(tmp_path):
    d = tmp_path / "r"
    shutil.copytree(FIX, d)
    rows = list(csv.DictReader(open(d / "runs.csv")))
    rows[0]["zip_sha256"] = ""
    with open(d / "runs.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert any("zip_sha256" in p for p in runs.validate_dir(d))
