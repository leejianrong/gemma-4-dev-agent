from analysis.trace_questions import edit_followups, message_lengths, milestones, summarize_runs
from tests.unit.test_trace_review import fabricated, step


def trace_with_messages(lens):
    steps = [{"source": "system", "message": "prompt"}]
    for n in lens:
        s = step("read_file", {"filepath": "a.py"})
        s["message"] = "x" * n
        steps.append(s)
    return {"steps": steps}


def test_message_lengths_follow_agent_steps_in_order_and_treat_missing_as_zero():
    t = trace_with_messages([300, 40])
    del t["steps"][2]["message"]
    assert message_lengths(t) == [300, 0]


def test_edit_followups_classify_the_call_after_each_refused_edit():
    t = fabricated()  # one refused edit_file on src/a.py, then edit_file on the same path
    assert edit_followups(t) == {"refused": 1, "retry_edit": 1, "reread": 0, "other": 0, "last": 0}


def test_edit_followups_count_a_refusal_with_nothing_after_it_as_last():
    t = {"steps": [step("edit_file", {"filepath": "a.py"}, status="error")]}
    assert edit_followups(t)["last"] == 1


def test_milestones_give_call_index_and_seconds_at_first_edit_test_and_submit():
    m = milestones(fabricated())
    assert m["first_edit"] == (4, 11.0)  # 0-based call index, elapsed seconds
    assert m["first_test"] == (6, 20.0)
    assert m["submit"] == (7, 21.0)
    assert m["calls"] == 8


def test_milestones_use_none_when_an_event_never_happens():
    m = milestones({"steps": [step("read_file", {"filepath": "a.py"})]})
    assert m["first_edit"] is None and m["first_test"] is None and m["submit"] is None


def test_summarize_runs_splits_resolved_from_unresolved_and_reports_only_aggregates():
    rows = [
        {"resolved": True, "m": milestones(fabricated()), "msg": [400, 50, 40]},
        {"resolved": False, "m": milestones(fabricated()), "msg": [400, 80, 0]},
    ]
    out = summarize_runs(rows)
    assert out["resolved"]["n"] == 1 and out["unresolved"]["n"] == 1
    assert out["resolved"]["median_first_edit_call"] == 4
    assert out["all"]["msg_median_by_call"][0] == 400
    assert "instance" not in str(out)


def test_edit_followups_ignore_edits_refused_only_because_the_budget_ran_out():
    t = {
        "steps": [
            step("edit_file", {"filepath": "a.py"}, status="error", etype="BudgetExceeded"),
            step("edit_file", {"filepath": "a.py"}, status="error", etype="FileEditError"),
        ]
    }
    out = edit_followups(t)
    assert out["refused"] == 1 and out["last"] == 1
