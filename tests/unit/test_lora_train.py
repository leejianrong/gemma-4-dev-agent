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
