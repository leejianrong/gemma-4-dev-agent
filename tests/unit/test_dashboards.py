import json
import shutil
import urllib.request

import pytest

pytest.importorskip("indah")
from dashboards import app as dash_app  # noqa: E402
from dashboards import data as rundata  # noqa: E402
from dashboards import pages  # noqa: E402


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
