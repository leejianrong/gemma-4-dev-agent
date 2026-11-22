import json

from analysis import teacher_dataset as td


def step(i, calls=None, msg=None, src="agent", obs="{}"):
    s = {"step_id": i, "source": src, "message": msg}
    if calls:
        s["tool_calls"] = [
            {"tool_call_id": f"c{i}", "function_name": n, "arguments": a} for n, a in calls
        ]
        s["observation"] = {"content": obs}
    return s


def trace(*agent):
    head = [step(1, src="system", msg="sys"), step(2, src="user", msg="issue")]
    return {"steps": head + list(agent)}


GOOD = trace(
    step(3, [("read_file", {"filepath": "a.py"})]),
    step(4, [("edit_file", {"filepath": "a.py", "old_string": "x", "new_string": "y"})]),
    step(5, [("submit_patch", {})]),
    step(6, msg="Done"),
)


def test_steps_become_chat_turns_with_json_string_arguments():
    msgs = td.to_messages(GOOD)
    assert [m["role"] for m in msgs] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    call = msgs[2]["tool_calls"][0]
    assert call["function"]["name"] == "read_file"
    assert json.loads(call["function"]["arguments"]) == {"filepath": "a.py"}
    assert msgs[3]["tool_call_id"] == call["id"]


def test_a_clean_resolved_run_is_kept():
    assert td.reject_reason(td.to_messages(GOOD)) is None


def test_runs_without_a_submit_or_an_edit_or_with_a_loop_are_dropped():
    no_submit = trace(step(3, [("edit_file", {"a": 1})]), step(4, msg="Done"))
    assert td.reject_reason(td.to_messages(no_submit)) == "no submit_patch"
    no_edit = trace(step(3, [("read_file", {"a": 1})]), step(4, [("submit_patch", {})]))
    assert td.reject_reason(td.to_messages(no_edit)) == "no edit"
    same = [("run_command", {"command": "ls"})]
    loop = trace(
        *[step(3 + i, same) for i in range(3)],
        step(9, [("edit_file", {})]),
        step(10, [("submit_patch", {})]),
    )
    assert td.reject_reason(td.to_messages(loop)) == "repeated call loop"


def test_a_text_only_turn_in_the_middle_is_dropped():
    mid = trace(
        step(3, msg="let me think"), step(4, [("edit_file", {})]), step(5, [("submit_patch", {})])
    )
    assert td.reject_reason(td.to_messages(mid)) == "text-only turn before the end"


def test_build_reads_the_resolved_column_as_the_runner_writes_it(tmp_path):
    (tmp_path / "raw" / "traces").mkdir(parents=True)
    (tmp_path / "raw" / "traces" / "trace_t_1.json").write_text(json.dumps(GOOD))
    (tmp_path / "task_results.csv").write_text(
        "instance_id,repo,resolved\nt_1,synthetic/toolz,1\nt_2,synthetic/toolz,0\n"
    )
    kept, stats = td.build([tmp_path], [], val_repo="toolz")
    assert [r["id"] for r in kept] == ["t_1"]
    assert kept[0]["meta"]["split"] == "val" and stats["resolved"] == 1


def test_a_malformed_call_and_its_nudge_are_removed_and_the_run_is_kept():
    broken = trace(
        step(3, msg='<invoke:bash {"tool": "run_command"}'),
        step(4, src="system", msg="Please continue your work"),
        step(5, [("edit_file", {"filepath": "a.py"})]),
        step(6, [("submit_patch", {})]),
        step(7, msg="Done"),
    )
    msgs, removed = td.repair(td.to_messages(broken))
    assert removed == 1 and td.reject_reason(msgs) is None
    assert all(m["role"] != "system" for m in msgs[2:])
