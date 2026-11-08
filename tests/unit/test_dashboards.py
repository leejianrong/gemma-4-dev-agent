import json
import shutil
import urllib.request

import pytest

pytest.importorskip("indah")
from dashboards import app as dash_app  # noqa: E402
from dashboards import data as rundata  # noqa: E402
from dashboards import pages  # noqa: E402


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Never read whatever real data happens to be under data/."""
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "no-runs"))
    monkeypatch.setenv("LOCALIZE_DIR", str(tmp_path / "no-localize"))


def test_with_no_runs_the_fixtures_are_used_and_flagged(tmp_path):
    d = rundata.load(tmp_path / "none")
    assert d.is_fixture and len(d.runs) == 2 and len(d.tasks) == 6


def test_real_runs_replace_the_fixtures_and_subfolders_are_merged(tmp_path):
    for name in ("k1", "k2"):
        shutil.copytree(rundata.FIXTURES, tmp_path / name)
    d = rundata.load(tmp_path)
    assert not d.is_fixture and len(d.runs) == 4 and len(d.sources) == 2


def test_every_registered_page_builds_on_the_fixtures():
    d = rundata.load()
    for title, build in pages.PAGES:
        assert build(d) is not None, title


def test_the_app_boots_on_a_free_port_and_serves_the_shell():
    import indah

    handle = indah.launch(dash_app.create(), block=False, open_inline=False)
    try:
        with urllib.request.urlopen(handle.url, timeout=10) as r:
            body = r.read().decode()
            assert r.status == 200 and "<html" in body.lower()
        url = handle.url.rstrip("/") + "/api/stream"
        with urllib.request.urlopen(url, timeout=10) as r:
            init = ""
            for raw in r:
                line = raw.decode()
                if line.startswith("data:") and '"type":"init"' in line.replace(" ", ""):
                    init = line
                    break
        tree = json.loads(init[len("data:") :])
        text = json.dumps(tree)
        assert "Runs overview" in text and "fixture" in text and "prompt_v2" in text
    finally:
        handle.stop()


def test_localization_tables_follow_the_repo_and_pool_filters():
    from dashboards import localization as lz

    loc = lz.load(None)
    assert loc.is_fixture and lz.repos(loc)[0] == "all repos"
    rows = lz.method_rows(loc, "all repos", "library")
    assert {r["method"] for r in rows} >= {"BM25", "random"}
    assert all({"recall@1", "recall@5", "recall@10"} <= set(r) for r in rows)
    chart = lz.chart_rows(loc, "all repos", "library")
    assert [c[0] for c in chart] == [1, 5, 10] and len(chart[0]) == len(rows) + 1
    assert lz.task_ids(loc, "Textualize/rich", "library") == ["rich_0002"]


def test_a_tasks_ranked_list_marks_gold_nodes_and_lists_misses():
    from dashboards import localization as lz

    loc = lz.load(None)
    rows = lz.ranked_rows(loc, "fastapi_0001", "library", "bm25")
    assert rows[0]["rank"] == 1 and rows[0]["gold"] == "GOLD"
    assert sum(r["gold"] == "GOLD" for r in rows) == 2
    assert lz.ranked_rows(loc, "nope", "library", "bm25") == []
    t = loc.tasks[0]
    t["top"] = "a|b"
    t["gold"] = "z"
    miss = lz.ranked_rows(loc, t["instance_id"], t["pool"], t["method"])
    assert miss[-1] == {"rank": ">20", "node": "z", "gold": "GOLD (not in top 20)"}


def test_the_app_tree_includes_the_localization_page():
    import indah

    handle = indah.launch(dash_app.create(), block=False, open_inline=False)
    try:
        with urllib.request.urlopen(handle.url.rstrip("/") + "/api/stream", timeout=10) as r:
            for raw in r:
                line = raw.decode()
                if '"type":"init"' in line.replace(" ", ""):
                    break
        assert "Localization benchmark" in line and "BM25" in line
    finally:
        handle.stop()


def test_the_noise_page_builds_and_reaches_the_app_tree():
    import indah

    handle = indah.launch(dash_app.create(), block=False, open_inline=False)
    try:
        with urllib.request.urlopen(handle.url.rstrip("/") + "/api/stream", timeout=10) as r:
            for raw in r:
                line = raw.decode()
                if '"type":"init"' in line.replace(" ", ""):
                    break
        assert "Noise and replicate planner" in line and "one task is worth" in line
    finally:
        handle.stop()
