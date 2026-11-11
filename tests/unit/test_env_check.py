import io
import json
import tarfile

from pod import env_check

TEST_PATCH = """--- /dev/null
+++ b/tests/test_calc.py
@@ -0,0 +1,4 @@
+from calc import add
+
+def test_add():
+    assert add(1, 2) == 3
"""
GOOD = """--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


def _snapshot(path):
    with tarfile.open(path, "w:gz") as tf:
        data = b"def add(a, b):\n    return a - b\n"
        info = tarfile.TarInfo("calc.py")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


def test_test_files_lists_only_touched_test_modules():
    assert env_check.test_files(TEST_PATCH) == ["tests/test_calc.py"]
    assert env_check.test_files(GOOD) == []


def test_a_correct_gold_patch_passes_and_a_wrong_one_fails(tmp_path):
    snap = tmp_path / "s.tgz"
    _snapshot(snap)
    ok, _ = env_check.check(
        {"patch": GOOD.rstrip("\n"), "test_patch": TEST_PATCH.rstrip("\n")}, snap
    )
    assert ok
    bad = GOOD.replace("+    return a + b", "+    return a * b")
    ok, tail = env_check.check({"patch": bad, "test_patch": TEST_PATCH}, snap)
    assert not ok and "failed" in tail


def test_main_fails_when_any_control_fails(tmp_path, capsys):
    data = tmp_path / "data"
    (data / "snapshots").mkdir(parents=True)
    _snapshot(data / "snapshots" / "t_1.tgz")
    task = {"instance_id": "t_1", "patch": GOOD, "test_patch": TEST_PATCH}
    (data / "tasks.jsonl").write_text(json.dumps(task) + "\n")
    assert env_check.main(["x", str(data), "t_1"]) == 0
    task["patch"] = GOOD.replace("+    return a + b", "+    return 0")
    (data / "tasks.jsonl").write_text(json.dumps(task) + "\n")
    assert env_check.main(["x", str(data), "t_1"]) == 1
    assert "env-check FAIL t_1" in capsys.readouterr().out
