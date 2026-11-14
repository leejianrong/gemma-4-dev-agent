import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("fetch_data", Path("scripts/fetch_data.py"))
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)

PAGE = """name,size,creationDate
tasks.jsonl,10,2026-10-13
graphs/a.json,5,2026-10-13
snapshots/x_1.tgz,100,2026-10-13
snapshots/y_2.tgz,200,2026-10-13
Next Page Token = abc123
"""


def test_parse_listing_reads_rows_and_token():
    rows, tok = fd.parse_listing(PAGE)
    assert rows[0] == ("tasks.jsonl", 10) and len(rows) == 4 and tok == "abc123"


def test_wanted_filters_snapshots_by_mode():
    rows, _ = fd.parse_listing(PAGE)
    assert [n for n, _ in fd.wanted(rows, "none", set())] == ["tasks.jsonl", "graphs/a.json"]
    assert "snapshots/x_1.tgz" in [n for n, _ in fd.wanted(rows, "scored", {"x_1"})]
    assert "snapshots/y_2.tgz" not in [n for n, _ in fd.wanted(rows, "scored", {"x_1"})]
    assert len(fd.wanted(rows, "all", set())) == 4


def test_test_dependency_wheels_come_with_snapshots_only():
    rows = [("tasks.jsonl", 1), ("wheels/a.whl", 2), ("snapshots/x_1.tgz", 3)]
    assert "wheels/a.whl" not in [n for n, _ in fd.wanted(rows, "none", set())]
    assert "wheels/a.whl" in [n for n, _ in fd.wanted(rows, "scored", {"x_1"})]


def _fake_cli(layout):
    """A stand-in for `kaggle competitions download -f NAME -p DIR`; layout says where it writes."""

    def run(cmd, **_):
        name, out = cmd[cmd.index("-f") + 1], Path(cmd[cmd.index("-p") + 1])
        dest = out / name if layout == "keeps-subfolder" else out / Path(name).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"12345")
        return SimpleNamespace(stdout="", stderr="")

    return run


def test_fetch_one_accepts_both_kaggle_cli_layouts(tmp_path, monkeypatch):
    # kaggle CLI 2.x writes embeddings/x.npz under -p as embeddings/x.npz; older ones flattened it.
    for layout in ("keeps-subfolder", "flat"):
        dest = tmp_path / layout
        monkeypatch.setattr(fd.subprocess, "run", _fake_cli(layout))
        monkeypatch.setattr(fd.time, "sleep", lambda _: None)
        assert fd.fetch_one("embeddings/x.npz", 5, dest, tries=1)
        assert (dest / "embeddings" / "x.npz").is_file()
        assert not (dest / "embeddings" / "embeddings").exists()
