from __future__ import annotations

import dataclasses

import pytest

from src.context.context_file import ContextFile
from src.context.context_snapshot import ContextSnapshot


def test_context_file_holds_path_and_reason() -> None:
    file = ContextFile(path="src/auth.py", reason="task keyword match")

    assert file.path == "src/auth.py"
    assert file.reason == "task keyword match"


def test_context_file_is_frozen() -> None:
    file = ContextFile(path="src/auth.py", reason="task keyword match")

    with pytest.raises(dataclasses.FrozenInstanceError):
        file.path = "src/other.py"


def test_context_snapshot_defaults_to_empty() -> None:
    snapshot = ContextSnapshot()

    assert snapshot.files == []
    assert snapshot.project_tree == ""


def test_context_snapshot_holds_files_and_project_tree() -> None:
    file = ContextFile(path="src/auth.py", reason="task keyword match")

    snapshot = ContextSnapshot(
        files=[file], project_tree="src/\n  auth.py"
    )

    assert snapshot.files == [file]
    assert snapshot.project_tree == "src/\n  auth.py"


def test_context_snapshot_is_frozen() -> None:
    snapshot = ContextSnapshot()

    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.project_tree = "x"
