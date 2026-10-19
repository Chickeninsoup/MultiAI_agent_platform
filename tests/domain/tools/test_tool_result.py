from __future__ import annotations

from src.domain.tools.tool_result import ToolResult


def test_to_dict_and_from_dict_roundtrip() -> None:
    result = ToolResult(
        tool_call_id="toolu_1",
        tool_name="write_file",
        success=True,
        output="ok",
        error_code=None,
        metadata={"duration_ms": 3},
    )

    assert ToolResult.from_dict(result.to_dict()) == result


def test_to_dict_and_from_dict_roundtrip_with_error() -> None:
    result = ToolResult(
        tool_call_id="toolu_1",
        tool_name="write_file",
        success=False,
        output="boom",
        error_code="TOOL_EXECUTION_FAILED",
    )

    assert ToolResult.from_dict(result.to_dict()) == result


def test_from_dict_defaults_missing_optional_fields() -> None:
    result = ToolResult.from_dict(
        {
            "tool_call_id": "toolu_1",
            "tool_name": "write_file",
            "success": True,
            "output": "ok",
        }
    )

    assert result.error_code is None
    assert result.metadata == {}
