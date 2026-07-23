from pathlib import Path

import pytest

from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.handlers.patch_file_tool import (
    PatchAmbiguousMatchError,
    PatchFileInput,
    PatchFileNotFoundError,
    PatchFileTool,
    PatchMatchNotFoundError,
)
from src.services.tools.path_guard import PathSecurityError


def test_definition_uses_safe_schema() -> None:
    definition = PatchFileTool.definition

    assert definition.name == "patch_file"
    assert definition.input_schema["required"] == [
        "path",
        "old_text",
        "new_text",
    ]
    assert definition.input_schema["additionalProperties"] is False


def test_valid_input() -> None:
    result = PatchFileTool.validate_input(
        {
            "path": "src/main.py",
            "old_text": "old",
            "new_text": "new",
        }
    )

    assert result == PatchFileInput(
        path="src/main.py",
        old_text="old",
        new_text="new",
    )


def test_empty_new_text_allowed() -> None:
    result = PatchFileTool.validate_input(
        {
            "path": "test.py",
            "old_text": "remove",
            "new_text": "",
        }
    )

    assert result.new_text == ""


@pytest.mark.parametrize(
    "tool_input",
    [
        None,
        [],
        "text",
        123,
    ],
)
def test_reject_non_object(
    tool_input: object,
) -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool.validate_input(tool_input)  # type: ignore[arg-type]


def test_reject_empty_old_text() -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool.validate_input(
            {
                "path": "a.py",
                "old_text": "",
                "new_text": "x",
            }
        )


def test_reject_missing_path() -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool.validate_input(
            {
                "old_text": "x",
                "new_text": "y",
            }
        )


def test_reject_non_string_new_text() -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool.validate_input(
            {
                "path": "a.py",
                "old_text": "x",
                "new_text": 123,
            }
        )


def test_reject_extra_fields() -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool.validate_input(
            {
                "path": "a.py",
                "old_text": "x",
                "new_text": "y",
                "command": "rm -rf",
            }
        )


def test_reject_null_byte_path() -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool.validate_input(
            {
                "path": "a\x00.py",
                "old_text": "x",
                "new_text": "y",
            }
        )


def test_find_patch_location_returns_unique_index() -> None:
    index = PatchFileTool.find_patch_location(
        "hello\nworld\n",
        "world",
    )

    assert index == 6


def test_find_patch_location_rejects_missing_text() -> None:
    with pytest.raises(PatchMatchNotFoundError):
        PatchFileTool.find_patch_location(
            "hello\n",
            "missing",
        )


def test_find_patch_location_rejects_ambiguous_match() -> None:
    with pytest.raises(PatchAmbiguousMatchError):
        PatchFileTool.find_patch_location(
            "x\nx\n",
            "x",
        )


def test_load_target_content_rejects_missing_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(PatchFileNotFoundError):
        PatchFileTool.load_target_content(
            tmp_path / "missing.py"
        )


def test_load_target_content_rejects_directory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "folder"
    directory.mkdir()

    with pytest.raises(PatchFileNotFoundError):
        PatchFileTool.load_target_content(directory)


def test_preview_patch_success(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"
    target.write_text(
        "hello\nworld\n",
        encoding="utf-8",
    )

    result = PatchFileTool.preview_patch(
        repository_root=tmp_path,
        path="test.py",
        old_text="hello",
        new_text="hi",
    )

    assert result["updated_content"] == (
        "hi\nworld\n"
    )
    assert result["match_index"] == 0
    assert result["old_length"] == len("hello")
    assert result["new_length"] == len("hi")

    # the file on disk is untouched
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"


def test_preview_patch_deletes_text_when_new_text_is_empty(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"
    target.write_text(
        "debug=True\nrest\n",
        encoding="utf-8",
    )

    result = PatchFileTool.preview_patch(
        repository_root=tmp_path,
        path="test.py",
        old_text="debug=True\n",
        new_text="",
    )

    assert result["updated_content"] == "rest\n"


def test_preview_patch_missing_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(PatchFileNotFoundError):
        PatchFileTool.preview_patch(
            repository_root=tmp_path,
            path="missing.py",
            old_text="a",
            new_text="b",
        )


def test_preview_patch_old_text_missing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    target.write_text(
        "hello",
        encoding="utf-8",
    )

    with pytest.raises(PatchMatchNotFoundError):
        PatchFileTool.preview_patch(
            repository_root=tmp_path,
            path="test.py",
            old_text="abc",
            new_text="x",
        )


def test_preview_patch_ambiguous(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    target.write_text(
        "x\nx\n",
        encoding="utf-8",
    )

    with pytest.raises(PatchAmbiguousMatchError):
        PatchFileTool.preview_patch(
            repository_root=tmp_path,
            path="test.py",
            old_text="x",
            new_text="y",
        )


def test_preview_patch_rejects_path_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "outside.py"
    outside_file.write_text("secret", encoding="utf-8")

    with pytest.raises(PathSecurityError):
        PatchFileTool.preview_patch(
            repository_root=repository_root,
            path="../outside.py",
            old_text="secret",
            new_text="leaked",
        )


def test_apply_patch_success(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    target.write_text(
        "hello\nworld\n",
        encoding="utf-8",
    )

    metadata = PatchFileTool.apply_patch(
        repository_root=tmp_path,
        path="test.py",
        old_text="hello",
        new_text="hi",
    )

    assert target.read_text(
        encoding="utf-8"
    ) == "hi\nworld\n"

    assert metadata["operation"] == "patch"
    assert metadata["path"] == "test.py"
    assert metadata["before_sha256"] != (
        metadata["after_sha256"]
    )
    assert metadata["bytes_written"] == len(
        "hi\nworld\n".encode("utf-8")
    )
    assert "updated_content" not in metadata


def test_apply_patch_delete_text(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    target.write_text(
        "remove\nkeep\n",
        encoding="utf-8",
    )

    PatchFileTool.apply_patch(
        repository_root=tmp_path,
        path="test.py",
        old_text="remove\n",
        new_text="",
    )

    assert target.read_text(
        encoding="utf-8"
    ) == "keep\n"


def test_apply_patch_failure_does_not_modify_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    original = "hello\n"

    target.write_text(
        original,
        encoding="utf-8",
    )

    with pytest.raises(
        PatchMatchNotFoundError
    ):
        PatchFileTool.apply_patch(
            repository_root=tmp_path,
            path="test.py",
            old_text="missing",
            new_text="new",
        )

    assert target.read_text(
        encoding="utf-8"
    ) == original


def test_apply_patch_ambiguous_does_not_modify_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    original = "x\nx\n"

    target.write_text(
        original,
        encoding="utf-8",
    )

    with pytest.raises(PatchAmbiguousMatchError):
        PatchFileTool.apply_patch(
            repository_root=tmp_path,
            path="test.py",
            old_text="x",
            new_text="y",
        )

    assert target.read_text(encoding="utf-8") == original


def test_apply_patch_missing_file_raises(
    tmp_path: Path,
) -> None:
    with pytest.raises(PatchFileNotFoundError):
        PatchFileTool.apply_patch(
            repository_root=tmp_path,
            path="missing.py",
            old_text="x",
            new_text="y",
        )


def test_apply_patch_rejects_path_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "outside.py"
    outside_file.write_text("secret", encoding="utf-8")

    with pytest.raises(PathSecurityError):
        PatchFileTool.apply_patch(
            repository_root=repository_root,
            path="../outside.py",
            old_text="secret",
            new_text="leaked",
        )

    assert outside_file.read_text(encoding="utf-8") == "secret"


def test_apply_patch_does_not_leave_temporary_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"
    target.write_text("hello\n", encoding="utf-8")

    PatchFileTool.apply_patch(
        repository_root=tmp_path,
        path="test.py",
        old_text="hello",
        new_text="hi",
    )

    assert list(tmp_path.iterdir()) == [target]


def test_execute_returns_mutation_metadata(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"

    target.write_text(
        "old\n",
        encoding="utf-8",
    )

    result = PatchFileTool().execute(
        tool_call_id="call-1",
        tool_input={
            "path": "test.py",
            "old_text": "old",
            "new_text": "new",
        },
        repository_root=tmp_path,
        max_output_chars=1000,
    )

    assert result.success is True
    assert result.tool_name == "patch_file"
    assert result.metadata["operation"] == "patch"
    assert result.metadata["path"] == "test.py"
    assert (
        result.metadata["before_sha256"]
        != result.metadata["after_sha256"]
    )
    assert target.read_text(encoding="utf-8") == "new\n"


def test_execute_raises_on_invalid_input(
    tmp_path: Path,
) -> None:
    with pytest.raises(InvalidToolInputError):
        PatchFileTool().execute(
            tool_call_id="call-1",
            tool_input={"old_text": "x", "new_text": "y"},
            repository_root=tmp_path,
            max_output_chars=1000,
        )


def test_execute_propagates_match_not_found(
    tmp_path: Path,
) -> None:
    target = tmp_path / "test.py"
    target.write_text("hello\n", encoding="utf-8")

    with pytest.raises(PatchMatchNotFoundError):
        PatchFileTool().execute(
            tool_call_id="call-1",
            tool_input={
                "path": "test.py",
                "old_text": "missing",
                "new_text": "x",
            },
            repository_root=tmp_path,
            max_output_chars=1000,
        )
