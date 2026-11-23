import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import lora_train as lt  # noqa: E402


def test_tool_call_arguments_become_dicts_like_vllm_before_templating():
    call = {
        "id": "c",
        "type": "function",
        "function": {"name": "run_command", "arguments": '{"command": "ls"}'},
    }
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "content": "x"},
    ]
    out = lt.template_view(msgs)
    assert out[0]["tool_calls"][0]["function"]["arguments"] == {"command": "ls"}
    assert out[1] == msgs[1]
    assert json.loads(call["function"]["arguments"]) == {"command": "ls"}  # input is untouched


def _call(name):
    return {"id": "c", "type": "function", "function": {"name": name, "arguments": "{}"}}


def test_edit_only_loss_picks_edit_and_submit_turns():
    msgs = [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": None, "tool_calls": [_call("run_command")]},
        {"role": "tool", "content": "x"},
        {"role": "assistant", "content": None, "tool_calls": [_call("edit_file")]},
        {"role": "tool", "content": "x"},
        {"role": "assistant", "content": None, "tool_calls": [_call("submit_patch")]},
        {"role": "assistant", "content": "done"},
    ]
    assert lt.loss_turns(msgs, edit_only=True) == [3, 5]
    assert lt.loss_turns(msgs, edit_only=False) == [1, 3, 5, 6]
