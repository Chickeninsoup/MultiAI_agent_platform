from pathlib import Path

import pytest

from src.services.tools.path_guard import (
    PathNotFoundError,
    PathSecurityError,
    resolve_repository_path,
    resolve_repository_write_path,
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


def test_write_path_resolves_new_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    result = resolve_repository_write_path(
        repository_root,
        "new_file.txt",
    )

    assert result == (
        repository_root.resolve() / "new_file.txt"
    )
    assert not result.exists()


def test_write_path_resolves_existing_file(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    existing_file = repository_root / "existing.txt"
    existing_file.write_text("hello", encoding="utf-8")

    result = resolve_repository_write_path(
        repository_root,
        "existing.txt",
    )

    assert result == existing_file.resolve()


def test_write_path_rejects_missing_parent_directory(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    with pytest.raises(PathNotFoundError):
        resolve_repository_write_path(
            repository_root,
            "missing_dir/new_file.txt",
        )


def test_write_path_rejects_parent_directory_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    with pytest.raises(PathSecurityError):
        resolve_repository_write_path(
            repository_root,
            "../outside.txt",
        )


def test_write_path_rejects_absolute_path_outside_repository(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "outside.txt"

    with pytest.raises(PathSecurityError):
        resolve_repository_write_path(
            repository_root,
            str(outside_file),
        )


def test_write_path_rejects_symbolic_link_parent_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()

    symbolic_link = repository_root / "escape-link"

    try:
        symbolic_link.symlink_to(
            outside_directory,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("Symbolic links are unavailable.")

    with pytest.raises(PathSecurityError):
        resolve_repository_write_path(
            repository_root,
            "escape-link/new_file.txt",
        )


def test_write_path_rejects_symbolic_link_target_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    symbolic_link = repository_root / "escape-link.txt"

    try:
        symbolic_link.symlink_to(outside_file)
    except OSError:
        pytest.skip("Symbolic links are unavailable.")

    with pytest.raises(PathSecurityError):
        resolve_repository_write_path(
            repository_root,
            "escape-link.txt",
        )