"""Arm A12: the whitespace-tolerant edit skill script."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "experiments" / "skills" / "edit" / "scripts" / "edit.py"
spec = importlib.util.spec_from_file_location("skill_edit", PATH)
ed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ed)

SRC = "def f(x):\n    if x > 1:\n        return 'a'\n    return 'b'\n"


def run(tmp_path, capsys, name, text, **opts):
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_bytes(text.encode())
    argv = ["edit.py", "--root", str(tmp_path), "--file", name]
    for k, v in opts.items():
        argv += [f"--{k}", v]
    rc = ed.ed_main(argv)
    return rc, capsys.readouterr().out, (tmp_path / name).read_bytes().decode()


def test_matches_despite_wrong_indentation_and_spacing(tmp_path, capsys):
    rc, out, text = run(
        tmp_path,
        capsys,
        "m.py",
        SRC,
        old="if  x > 1:\nreturn 'a'",
        new="if x >= 1:\n    return 'a'",
    )
    assert rc == 0 and "edited m.py" in out
    assert text == "def f(x):\n    if x >= 1:\n        return 'a'\n    return 'b'\n"


def test_new_text_takes_indent_of_replaced_block(tmp_path, capsys):
    rc, _, text = run(tmp_path, capsys, "m.py", SRC, old="return 'a'", new="        return 'z'")
    assert rc == 0 and "            return 'z'" not in text and "        return 'z'\n" in text


def test_line_range_mode(tmp_path, capsys):
    rc, out, text = run(tmp_path, capsys, "m.py", SRC, start="4", end="4", new="return 'c'")
    assert rc == 0 and text.endswith("    return 'c'\n") and "4  " in out


def test_ambiguous_match_lists_lines_and_leaves_file(tmp_path, capsys):
    src = "a = 1\nb = 2\na = 1\n"
    rc, out, text = run(tmp_path, capsys, "m.py", src, old="a = 1", new="a = 3")
    assert rc == 1 and "2 places" in out and "1, 3" in out and text == src


def test_not_found_shows_closest_line(tmp_path, capsys):
    rc, out, text = run(tmp_path, capsys, "m.py", SRC, old="if x > 2:", new="if x > 3:")
    assert rc == 1 and "NOT EDITED" in out and "Closest line" in out and text == SRC


def test_syntax_error_is_undone(tmp_path, capsys):
    rc, out, text = run(tmp_path, capsys, "m.py", SRC, old="return 'b'", new="return (")
    assert rc == 1 and "would not parse" in out and text == SRC


def test_test_files_and_outside_paths_refused(tmp_path, capsys):
    rc, out, _ = run(tmp_path, capsys, "tests/test_a.py", "x = 1\n", old="x = 1", new="x = 2")
    assert rc == 1 and "refused" in out
    rc = ed.ed_main(
        ["edit.py", "--root", str(tmp_path), "--file", "../x.py", "--old", "a", "--new", "b"]
    )
    assert rc == 1 and "outside" in capsys.readouterr().out


def test_crlf_and_missing_final_newline_preserved(tmp_path, capsys):
    rc, _, text = run(tmp_path, capsys, "m.py", "a = 1\r\nb = 2", old="a = 1", new="a = 5")
    assert rc == 0 and text == "a = 5\r\nb = 2"
