import json

import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("pandas")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from analysis import data, run_all, style  # noqa: E402


def test_palette_is_distinct_and_repos_keep_one_colour():
    assert len(set(style.PALETTE.values())) == len(style.PALETTE)
    assert len(set(style.REPO_COLORS.values())) == len(style.REPO_COLORS)
    assert style.short("fastapi/fastapi") == "fastapi"


def test_style_applies_shared_settings():
    style.apply()
    assert plt.rcParams["savefig.dpi"] == 200
    assert plt.rcParams["axes.spines.top"] is False


def test_save_writes_png_and_a_sidecar_naming_sources_and_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("FIG_DIR", str(tmp_path))
    fig, ax = plt.subplots(figsize=(style.FIG_WIDTH, 2))
    ax.plot([1, 2, 3])
    png = style.save(fig, "demo", ["tasks.csv", "hunks.csv"], {"tasks": 129}, "caption")
    assert png.is_file() and png.stat().st_size > 1000
    meta = json.loads((tmp_path / "demo.json").read_text())
    assert meta["data"] == ["hunks.csv", "tasks.csv"] and meta["numbers"] == {"tasks": 129}


def test_load_reads_csv_and_gz(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    pd.DataFrame({"a": [1, 2]}).to_csv(tmp_path / "t.csv", index=False)
    pd.DataFrame({"a": [3]}).to_csv(tmp_path / "g.csv.gz", index=False)
    assert list(data.load("t.csv")["a"]) == [1, 2]
    assert list(data.load("g.csv.gz")["a"]) == [3]


def test_missing_table_error_says_how_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="make pull-eda"):
        data.load("tasks.csv")


def test_run_all_reports_missing_data_as_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EDA_DIR", str(tmp_path))
    (tmp_path / "fakefig.py").write_text(
        "from analysis import data\n\n\ndef build():\n    data.load('tasks.csv')\n    return []\n"
    )
    import analysis

    monkeypatch.setattr(analysis, "__path__", [*analysis.__path__, str(tmp_path)])
    monkeypatch.setattr(run_all, "FIGURE_MODULES", ["fakefig"])
    assert run_all.main() == 1
    assert "make pull-eda" in capsys.readouterr().err
