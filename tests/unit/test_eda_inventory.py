import json

import pytest

pytest.importorskip("matplotlib")
pd = pytest.importorskip("pandas")

from analysis import eda_inventory  # noqa: E402


def tasks_csv(tmp_path, repos=("fastapi/fastapi", "Textualize/rich", "psf/requests")):
    rows = []
    for i, repo in enumerate(repos * 4):
        rows.append(
            {
                "instance_id": f"t{i}",
                "repo": repo,
                "created_at": f"2025-0{1 + i % 9}-15T10:00:00Z",
                "problem_words": 20 + 15 * i,
                "code_blocks": i % 2,
                "urls": i % 3 == 0,
                "has_traceback": 0,
                "hints_chars": 0,
            }
        )
    pd.DataFrame(rows).to_csv(tmp_path / "tasks.csv", index=False)
    return len(rows)


def test_build_writes_figure_and_a_sidecar_with_the_quoted_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "figs"))
    n = tasks_csv(tmp_path)
    [png] = eda_inventory.build()
    assert png.is_file() and png.stat().st_size > 5000
    meta = json.loads((tmp_path / "figs" / "eda_01_inventory.json").read_text())
    assert meta["data"] == ["tasks.csv"]
    assert meta["numbers"]["tasks"] == n
    assert meta["numbers"]["tasks_per_repo"] == {"fastapi": 4, "rich": 4, "requests": 4}
    assert meta["numbers"]["issues_with_traceback"] == 0
    assert str(n) in meta["caption"]


def test_a_single_task_repo_does_not_break_the_figure(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "figs"))
    tasks_csv(tmp_path, repos=("fastapi/fastapi", "encode/httpx"))
    rows = pd.read_csv(tmp_path / "tasks.csv")
    pd.concat(
        [rows[rows.repo == "fastapi/fastapi"], rows[rows.repo == "encode/httpx"].head(1)]
    ).to_csv(tmp_path / "tasks.csv", index=False)
    assert eda_inventory.build()[0].is_file()
