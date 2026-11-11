import importlib.util
from pathlib import Path

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
