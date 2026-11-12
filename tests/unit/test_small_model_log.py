from analysis import small_model_log as sml

BLOCK = """\
  [   0.0s] 📋 System Prompt: x
  [   4.1s] 💭 (120 chars) "think"
  [   4.1s] 📖 read_file (fastapi/a.py)
  [   4.1s]   ✓ {'status': 'ok'}
  [   7.8s] ✏️ edit_file (fastapi/a.py)
  [   7.8s]   ❌ {'status': 'error', 'error_type': 'FileEditError',
'error_message': 'Failed to replace: old_string not found.'}
  [   8.0s] ✏️ edit_file (fastapi/a.py)
  [   8.0s]   ❌ {'status': 'error', 'error_type': 'FileEditError',
'error_message': 'No changes to apply. old_string and new_string are identical'}
  [   9.0s] 🔧 run_command timeout 150 python -m pytest tests/test_a.py
  [   9.5s]   → ===== 1 failed, 2 passed in 0.4s =====
╰──────╯TASK 1/2 fastapi_1 status=unresolved calls=4 t=19.0
  [   0.0s] 📋 System Prompt: x
  [   2.0s] 💭 (300 chars) "again"
  [   2.5s] ✏️ edit_file (docs_src/b.py)
  [   2.6s] 🤖 submit_patch
╰──────╯TASK 2/2 fastapi_2 status=resolved calls=2 t=486.0
"""


def test_parse_reads_each_block_before_its_marker():
    a, b = sml.parse(BLOCK)
    assert (a["id"], a["status"], a["calls"]) == ("fastapi_1", "unresolved", 4)
    assert a["tools"] == {"read_file": 1, "edit_file": 2, "run_command": 1}
    assert a["errors"] == {"edit: old_string not found": 1, "edit: identical old and new string": 1}
    assert a["thoughts"] == [120] and a["tests"] == ["fail"]
    assert b["tools"]["submit_patch"] == 1 and b["edits"] == ["docs_src/b.py"]


def test_kind_calls_a_slow_error_a_timeout():
    assert sml.kind({"status": "error", "secs": 485.0}) == "timeout"
    assert sml.kind({"status": "error", "secs": 20.0}) == "error (other)"


def test_summarize_counts_without_ids():
    out = sml.summarize(sml.parse(BLOCK), {"fastapi_1": {"fastapi/a.py"}})
    assert out["errors_by_class"]["edit: old_string not found"] == 1
    assert out["no_submit_call"] == "1 of 2 (50%)"
    assert out["edited_a_gold_file"] == "1 of 2 (50%)"
    assert out["files_edited_by_kind"] == {"library": 1, "docs": 1}
    assert "fastapi_1" not in str(out)
