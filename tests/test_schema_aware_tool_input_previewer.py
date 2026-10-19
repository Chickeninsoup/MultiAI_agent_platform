from __future__ import annotations

from src.domain.tools.tool_call import ToolCall
from src.schema_aware_tool_input_previewer import (
    SchemaAwareToolInputPreviewer,
)

SECRET = "super-secret-token"


def _preview(name: str, input_: dict) -> str:
    return SchemaAwareToolInputPreviewer().preview(
        ToolCall(id="toolu_1", name=name, input=input_)
    )


def test_write_file_preview_shows_path_but_not_content() -> None:
    preview = _preview(
        "write_file", {"path": "a.py", "content": SECRET}
    )

    assert "a.py" in preview
    assert SECRET not in preview
    assert "content" not in preview


def test_patch_file_preview_shows_path_but_not_text_fields() -> None:
    preview = _preview(
        "patch_file",
        {
            "path": "a.py",
            "old_text": SECRET,
            "new_text": "replacement-secret",
        },
    )

    assert "a.py" in preview
    assert SECRET not in preview
    assert "replacement-secret" not in preview


def test_read_file_preview_shows_path_and_line_range() -> None:
    preview = _preview(
        "read_file", {"path": "a.py", "start_line": 1, "end_line": 10}
    )

    assert "a.py" in preview
    assert "start_line=1" in preview
    assert "end_line=10" in preview


def test_list_files_preview_shows_path_and_recursive() -> None:
    preview = _preview(
        "list_files", {"path": "src", "recursive": True}
    )

    assert "src" in preview
    assert "recursive=True" in preview


def test_git_status_preview_has_no_fields() -> None:
    preview = _preview("git_status", {})

    assert "git_status" in preview


def test_git_diff_preview_shows_staged_flag() -> None:
    preview = _preview("git_diff", {"staged": True})

    assert "staged=True" in preview


def test_run_test_preview_shows_test_name_only() -> None:
    preview = _preview("run_test", {"test_name": "unit"})

    assert "unit" in preview


def test_unsupported_tool_name_gives_honest_metadata_only_preview() -> None:
    preview = _preview(
        "future_tool", {"secret_field": SECRET, "other": "data"}
    )

    assert SECRET not in preview
    assert "data" not in preview
    assert "omitted" in preview.lower()


def test_preview_never_falls_back_to_repr_or_json_dump() -> None:
    """Regression: a previewer that fell back to repr()/json.dumps()
    of the full input would leak every field, including ones this
    previewer has never reviewed. Proven here by checking that no
    unreviewed field value ever appears, for both a known and an
    unknown tool."""

    preview = _preview(
        "write_file",
        {
            "path": "a.py",
            "content": SECRET,
            "mode": "overwrite",
        },
    )
    assert SECRET not in preview

    unknown_preview = _preview(
        "totally_unregistered_tool", {"anything": SECRET}
    )
    assert SECRET not in unknown_preview


def test_truncates_excessively_long_field_values() -> None:
    long_path = "a" * 1000
    preview = _preview("read_file", {"path": long_path})

    assert len(preview) < len(long_path)
    assert "truncated" in preview
