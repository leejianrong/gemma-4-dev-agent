import teacher_worker as tw


def test_a_tool_reply_becomes_a_semula_tool_call():
    got = tw.to_answer('```json\n{"tool": "read_file", "arguments": {"path": "a.py"}}\n```')
    call = got["message"]["tool_calls"][0]["function"]
    assert call == {"name": "read_file", "arguments": {"path": "a.py"}}


def test_a_text_reply_ends_the_session_with_text():
    assert tw.to_answer('{"text": "Done"}') == {"content": "Done"}


def test_prose_or_an_empty_reply_is_never_an_empty_answer():
    assert tw.to_answer("I could not find it") == {"content": "I could not find it"}
    assert tw.to_answer("") == {"content": "Done."}
    assert (
        tw.to_answer('{"tool": "x", "arguments": "not an object"}')["message"]["tool_calls"][0][
            "function"
        ]["arguments"]
        == {}
    )
