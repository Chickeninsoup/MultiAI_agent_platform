from __future__ import annotations

from src.domain.tools.tool_call import ToolCall


def test_to_dict_and_from_dict_roundtrip() -> None:
    tool_call = ToolCall(
        id="toolu_1", name="write_file", input={"path": "a.py"}
    )

    assert ToolCall.from_dict(tool_call.to_dict()) == tool_call


def test_to_dict_shape() -> None:
    tool_call = ToolCall(
        id="toolu_1", name="write_file", input={"path": "a.py"}
    )

    assert tool_call.to_dict() == {
        "id": "toolu_1",
        "name": "write_file",
        "input": {"path": "a.py"},
    }
