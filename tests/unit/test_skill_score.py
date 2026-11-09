import io
import tarfile

import skill_score as ss


def make_tgz(path, files):
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo(".")
        info.type = tarfile.DIRTYPE
        tf.addfile(info)
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_read_py_keeps_only_library_python_and_strips_the_dot_prefix(tmp_path):
    make_tgz(
        tmp_path / "s.tgz",
        {
            "pkg/a.py": "def f():\n    pass\n",
            "tests/test_a.py": "def test_f():\n    pass\n",
            "pkg/notes.txt": "x",
        },
    )
    assert list(ss.ss_read_py(tmp_path / "s.tgz")) == ["pkg/a.py"]


def test_read_py_of_a_missing_file_is_empty(tmp_path):
    assert ss.ss_read_py(tmp_path / "nope.tgz") == {}


GRAPH = {"nodes": [{"id": "pkg.a.render_table"}, {"id": "pkg.a.open_socket"}, {"id": "tests.x"}]}
FILES = {"pkg/a.py": "def render_table():\n    pass\n\n\ndef open_socket():\n    pass\n"}
TASK = {"instance_id": "pkg_1", "repo": "o/pkg", "problem_statement": "render table is wrong"}


def test_task_rows_score_both_variants_against_the_graph_library_pool():
    rows = ss.ss_task_rows(TASK, GRAPH, FILES, {"pkg.a.render_table", "tests.x"})
    assert [r["method"] for r in rows] == ["skill_head", "skill_full"]
    assert rows[0]["n_gold_in_pool"] == 1  # tests.x is outside the library pool
    assert rows[0]["hit@1"] == 1.0 and rows[0]["coverage"] == 1.0


def test_a_gold_node_the_skill_cannot_list_is_a_miss_with_lower_coverage():
    graph = {"nodes": GRAPH["nodes"] + [{"id": "pkg.a.hidden"}]}
    rows = ss.ss_task_rows(TASK, graph, FILES, {"pkg.a.hidden"})
    assert rows[0]["hit@10"] == 0.0 and rows[0]["coverage"] == 0.0


def test_task_without_a_library_gold_node_gives_no_rows():
    assert ss.ss_task_rows(TASK, GRAPH, FILES, {"tests.x"}) == []


def test_timing_reports_median_and_coverage_per_variant():
    rows = [
        {"method": "skill_head", "seconds": s, "coverage": c}
        for s, c in [(1.0, 1.0), (3.0, 0.5), (2.0, 1.0)]
    ]
    t = ss.ss_timing(rows)["head"]
    assert t["median_s"] == 2.0 and t["max_s"] == 3.0 and t["mean_gold_coverage"] == 0.833
