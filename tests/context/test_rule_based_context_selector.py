from __future__ import annotations

from pathlib import Path

from src.context.rule_based_context_selector import (
    FALLBACK_FILES,
    RuleBasedContextSelector,
)


def _write(repository_root: Path, relative_path: str) -> None:
    file_path = repository_root / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("placeholder\n", encoding="utf-8")


def test_keyword_match_selects_the_relevant_file(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/auth.py")
    _write(tmp_path, "src/database.py")
    selector = RuleBasedContextSelector()

    snapshot = selector.select("fix authentication bug", tmp_path)

    paths = {file.path for file in snapshot.files}
    assert paths == {"src/auth.py"}


def test_matched_file_reason_explains_the_keyword_match(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/auth.py")
    selector = RuleBasedContextSelector()

    snapshot = selector.select("fix authentication bug", tmp_path)

    assert "keyword match" in snapshot.files[0].reason


def test_multiple_files_can_match_different_keywords(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/auth/login.py")
    _write(tmp_path, "tests/test_login.py")
    _write(tmp_path, "src/database.py")
    selector = RuleBasedContextSelector()

    snapshot = selector.select("implement login feature", tmp_path)

    paths = {file.path for file in snapshot.files}
    assert paths == {"src/auth/login.py", "tests/test_login.py"}


def test_no_keyword_match_falls_back_to_fallback_files(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/auth.py")
    _write(tmp_path, "src/database.py")
    selector = RuleBasedContextSelector()

    snapshot = selector.select("say hello", tmp_path)

    paths = [file.path for file in snapshot.files]
    assert paths == list(FALLBACK_FILES)
    assert all("fallback" in file.reason for file in snapshot.files)


def test_fallback_files_are_not_the_old_hardcoded_defaults() -> None:
    assert set(FALLBACK_FILES) != {
        "src/main.py",
        "src/models.py",
        "src/repositories.py",
        "src/run_service.py",
        "src/execution.py",
    }


def test_excluded_directories_are_never_selected(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/auth.py")
    _write(tmp_path, ".venv/auth/auth.py")
    _write(tmp_path, "__pycache__/auth.pyc")
    selector = RuleBasedContextSelector()

    snapshot = selector.select("fix authentication bug", tmp_path)

    paths = {file.path for file in snapshot.files}
    assert paths == {"src/auth.py"}
