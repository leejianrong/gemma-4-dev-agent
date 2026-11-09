import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "experiments" / "skills" / "localize" / "scripts" / "localize.py"
spec = importlib.util.spec_from_file_location("skill_localize", PATH)
sk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sk)

SRC = '''\
import os


def top(a):
    def inner():
        return 1
    return inner


async def fetch(url):
    return url


@decorator
class Box:
    """A box."""

    size = 3

    def open(self, lid,
             force=False):
        return lid

    @property
    def width(self):
        return 1

    @width.setter
    def width(self, v):
        self._w = v

    class Meta:
        def helper(self):
            return 2
'''


def ids(defs):
    return {d["id"]: d for d in defs}


def test_tokens_split_identifiers_and_keep_the_whole_word():
    t = sk.sk_tokens("parseHeader and get_user_id")
    assert {"parse", "header", "parseheader", "get", "user", "id"} <= set(t)
    assert "and" not in t


def test_module_id_drops_src_init_and_suffix():
    assert sk.sk_module_id("fastapi/routing.py") == "fastapi.routing"
    assert sk.sk_module_id("src/requests/models.py") == "requests.models"
    assert sk.sk_module_id("rich/__init__.py") == "rich"


def test_library_pool_matches_the_study_rule():
    assert sk.sk_is_library("rich/table.py")
    assert sk.sk_is_library("src/requests/api.py")
    assert not sk.sk_is_library("tests/test_x.py")
    assert not sk.sk_is_library("docs_src/app.py")
    assert not sk.sk_is_library("test_helpers.py")
    assert not sk.sk_is_library("README.md")


def test_defs_cover_functions_async_classes_and_methods_but_not_nested_functions():
    d = ids(sk.sk_defs(SRC, "pkg.mod"))
    assert set(d) == {
        "pkg.mod.top",
        "pkg.mod.fetch",
        "pkg.mod.Box",
        "pkg.mod.Box.open",
        "pkg.mod.Box.width",
        "pkg.mod.Box.Meta",
        "pkg.mod.Box.Meta.helper",
    }
    assert d["pkg.mod.fetch"]["line"] == 10
    assert d["pkg.mod.Box"]["line"] == 14  # the decorator line, where the definition starts


def test_duplicate_ids_are_merged_so_property_setters_are_one_candidate():
    d = ids(sk.sk_defs(SRC, "pkg.mod"))
    assert "self._w = v" in d["pkg.mod.Box.width"]["text"]
    assert "return 1" in d["pkg.mod.Box.width"]["text"]


def test_class_head_text_has_docstring_and_signatures_not_bodies():
    head = ids(sk.sk_defs(SRC, "pkg.mod", class_text="head"))["pkg.mod.Box"]["text"]
    assert "A box." in head and "def open(self, lid" in head and "force=False" in head
    assert "return lid" not in head
    full = ids(sk.sk_defs(SRC, "pkg.mod", class_text="full"))["pkg.mod.Box"]["text"]
    assert "return lid" in full


def test_unparsable_source_gives_no_candidates():
    assert sk.sk_defs("def broken(:\n", "m") == []


def test_index_skips_tests_and_non_python_and_keeps_the_path():
    files = {
        "pkg/a.py": "def render_table():\n    pass\n",
        "tests/test_a.py": "def test_render_table():\n    pass\n",
        "pkg/data.txt": "def nope(): pass",
    }
    cands = sk.sk_index(files)
    assert [c["id"] for c in cands] == ["pkg.a.render_table"]
    assert cands[0]["path"] == "pkg/a.py"


def test_rank_puts_the_matching_definition_first_and_breaks_ties_by_id():
    files = {
        "pkg/a.py": "def render_table_columns():\n    pass\n\n\ndef open_socket():\n    pass\n",
        "pkg/b.py": "def table_of_contents():\n    pass\n",
    }
    ranked = sk.sk_rank(sk.sk_index(files), "table columns render")
    assert ranked[0][0]["id"] == "pkg.a.render_table_columns"
    zero = [c["id"] for c, s in ranked if s == 0]
    assert zero == sorted(zero)


def test_format_lists_rank_id_and_location():
    files = {"pkg/a.py": "def render_table():\n    pass\n"}
    out = sk.sk_format(sk.sk_rank(sk.sk_index(files), "render table"), 5)
    assert " 1. pkg.a.render_table  pkg/a.py:1" in out


def test_cli_reads_the_workspace_and_prints_ranked_definitions(tmp_path, capsys):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def render_table():\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_render_table():\n    pass\n")
    assert sk.sk_main(["localize.py", "--root", str(tmp_path), "render", "table"]) == 0
    out = capsys.readouterr().out
    assert "pkg.a.render_table" in out and "test_render_table" not in out
