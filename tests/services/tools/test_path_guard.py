from pathlib import Path

import pytest

from src.services.tools.path_guard import (
    PathNotFoundError,
    PathSecurityError,
    resolve_repository_path,
)


def test_resolves_file_inside_repository(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text("hello", encoding="utf-8")

    result = resolve_repository_path(
        repository_root,
        "example.txt",
    )

    assert result == target_file.resolve()


def test_rejects_parent_directory_escape(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")

    with pytest.raises(PathSecurityError):
        resolve_repository_path(
            repository_root,
            "../outside.txt",
        )


def test_rejects_absolute_path_outside_repository(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")

    with pytest.raises(PathSecurityError):
        resolve_repository_path(
            repository_root,
            str(outside_file),
        )


def test_rejects_missing_path(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    with pytest.raises(PathNotFoundError):
        resolve_repository_path(
            repository_root,
            "missing.txt",
        )


def test_rejects_symbolic_link_escape(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()

    secret_file = outside_directory / "secret.txt"
    secret_file.write_text("secret", encoding="utf-8")

    symbolic_link = repository_root / "escape-link"

    try:
        symbolic_link.symlink_to(
            outside_directory,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("Symbolic links are unavailable.")

    with pytest.raises(PathSecurityError):
        resolve_repository_path(
            repository_root,
            "escape-link/secret.txt",
        )