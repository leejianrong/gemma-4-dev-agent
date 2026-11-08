import json

import pytest

pytest.importorskip("matplotlib")
pd = pytest.importorskip("pandas")

from analysis import eda_async_graph, eda_cochange, eda_localization  # noqa: E402


def write(tmp_path, folder, name, rows):
    d = tmp_path / folder
    d.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(d / name, index=False)


def test_localization_figure_reads_the_summary_and_names_its_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "f"))
    rows = []
    for repo in ("all repos", "fastapi/fastapi", "Textualize/rich", "psf/requests"):
        for pool in ("library", "all"):
            for m, _, _ in eda_localization.METHODS + [("random", "", "")]:
                rows.append(
                    {"repo": repo, "pool": pool, "method": m, "tasks": 10}
                    | {f"recall@{k}": 0.1 * k / 10 for k in (1, 5, 10)}
                    | {f"hit@{k}": 0.5 for k in (1, 5, 10)}
                )
    write(tmp_path, "localize", "localize_summary.csv", rows)
    (png,) = eda_localization.build()
    meta = json.loads(png.with_suffix(".json").read_text())
    assert meta["numbers"]["hit@10_library_bm25"] == 0.5 and "50%" in meta["caption"]


def test_cochange_figure_reads_pooled_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "f"))
    rows = [
        {
            "repo": "all repos",
            "method": m,
            "tasks": 5,
            "recall": 0.3,
            "precision": 0.2,
            "mean_set_size": 10.0,
            "median_lift": 12.0,
        }
        for m, _, _ in eda_cochange.METHODS
    ]
    write(tmp_path, "cochange", "cochange_summary.csv", rows)
    write(tmp_path, "cochange", "cochange_tasks.csv", [{"n_pool": 500}, {"n_pool": 700}])
    (png,) = eda_cochange.build()
    meta = json.loads(png.with_suffix(".json").read_text())
    assert meta["numbers"]["median_library_nodes_in_graph"] == 600.0 and "30%" in meta["caption"]


def test_async_figure_states_zero_of_n_from_the_mapping_report(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("FIG_DIR", str(tmp_path / "f"))
    (tmp_path / "map").mkdir()
    rep = {
        "defs_in_patched_files": {
            "async_defs": 9,
            "async_with_node": 0,
            "sync_defs": 90,
            "sync_with_node": 90,
        },
        "library_hunk_status": {"mapped": 5, "node_missing": 2},
        "tasks": 3,
        "tasks_with_a_mapped_node": 2,
    }
    (tmp_path / "map" / "report.json").write_text(json.dumps(rep))
    (png,) = eda_async_graph.build()
    assert "None of the 9 async" in json.loads(png.with_suffix(".json").read_text())["caption"]


def test_missing_data_names_the_make_target(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="make pull-localize"):
        eda_localization.build()
