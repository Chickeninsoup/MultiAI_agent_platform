import hashlib
from pathlib import Path

import pytest

from src.services.tools.file_writer import (
    atomic_write_text,
    calculate_sha256,
)


def test_calculate_sha256_matches_hashlib() -> None:
    assert calculate_sha256("hello") == hashlib.sha256(
        b"hello"
    ).hexdigest()


def test_calculate_sha256_handles_empty_string() -> None:
    assert calculate_sha256("") == hashlib.sha256(b"").hexdigest()


def test_atomic_write_text_creates_new_file(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "example.txt"

    atomic_write_text(target_path=target_path, content="hello\n")

    assert target_path.read_text(encoding="utf-8") == "hello\n"


def test_atomic_write_text_replaces_existing_file(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "example.txt"
    target_path.write_text("old", encoding="utf-8")

    atomic_write_text(target_path=target_path, content="new")

    assert target_path.read_text(encoding="utf-8") == "new"


def test_atomic_write_text_leaves_no_temporary_file(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "example.txt"

    atomic_write_text(target_path=target_path, content="hello")

    assert list(tmp_path.iterdir()) == [target_path]


def test_atomic_write_text_cleans_up_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "example.txt"

    def failing_replace(*args: object, **kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(
        "src.services.tools.file_writer.os.replace",
        failing_replace,
    )

    with pytest.raises(OSError):
        atomic_write_text(target_path=target_path, content="hello")

    assert list(tmp_path.iterdir()) == []
