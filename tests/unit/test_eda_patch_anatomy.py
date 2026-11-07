import json

import pytest

pytest.importorskip("matplotlib")
pd = pytest.importorskip("pandas")

from analysis import eda_patch_anatomy as pa  # noqa: E402


def write_tables(tmp_path):
    tasks = pd.DataFrame(
        [
            {"instance_id": "a", "repo": "fastapi/fastapi", "patch_files": 1, "patch_new_files": 0},
            {"instance_id": "b", "repo": "fastapi/fastapi", "patch_files": 3, "patch_new_files": 1},
            {"instance_id": "c", "repo": "Textualize/rich", "patch_files": 7, "patch_new_files": 0},
            {"instance_id": "d", "repo": "Textualize/rich", "patch_files": 1, "patch_new_files": 0},
            {"instance_id": "e", "repo": "psf/requests", "patch_files": 2, "patch_new_files": 0},
        ]
    )
    rows = [
        ("a", "fastapi/fastapi", 1, 1, 2, 10),  # library: removed 2, added 10
        ("b", "fastapi/fastapi", 1, 1, 0, 30),  # pure addition
        ("b", "fastapi/fastapi", 1, 0, 5, 5),  # docs_src hunk
        ("c", "Textualize/rich", 1, 1, 8, 9),
        ("d", "Textualize/rich", 1, 0, 1, 1),  # only non-library: no library code
        ("e", "psf/requests", 1, 1, 3, 4),
    ]
    hunks = pd.DataFrame(
        [
            {
                "instance_id": i,
                "repo": r,
                "is_python": py,
                "is_library": lib,
                "n_removed": rem,
                "n_added": add,
            }
            for i, r, py, lib, rem, add in rows
        ]
    )
    tasks.to_csv(tmp_path / "tasks.csv", index=False)
    hunks.to_csv(tmp_path / "hunks.csv", index=False)
    return tasks, hunks


def test_prepare_classifies_each_task_by_where_its_edits_land(tmp_path):
    tasks, hunks = write_tables(tmp_path)
    t = pa.prepare(tasks, hunks).set_index("instance_id")
    assert t.loc["a", "kind"] == "library only" and t.loc["a", "lib_lines"] == 12
    assert t.loc["b", "kind"] == "library + other python"
    assert t.loc["d", "kind"] == "no library code" and t.loc["d", "lib_lines"] == 0
    assert t.loc["c", "files_bucket"] == "6+" and t.loc["b", "files_bucket"] == "3"


def test_build_saves_the_figure_and_the_quoted_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "figs"))
    write_tables(tmp_path)
    [png] = pa.build()
    assert png.is_file() and png.stat().st_size > 5000
    meta = json.loads((tmp_path / "figs" / "eda_02_patch_anatomy.json").read_text())
    n = meta["numbers"]
    assert meta["data"] == ["hunks.csv", "tasks.csv"]
    assert n["tasks"] == 5 and n["tasks_without_library_code"] == 1
    assert n["pure_addition_tasks"] == 1 and n["tasks_with_a_new_file"] == 1
    assert n["non_python_hunks"] == 0 and n["max_library_lines_changed"] == 30
