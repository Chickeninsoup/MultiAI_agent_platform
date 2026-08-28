from pathlib import Path

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

EXCLUDED_FILE_NAMES = {
    ".env",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def is_excluded(relative_path: Path) -> bool:
    """Shared noise filter for repository_root-relative paths.

    Lives here (not in RunContextBuilder) so RuleBasedContextSelector
    can reuse the same exclusion rules without importing
    RunContextBuilder - context_builder.py already imports from
    src.context, so the reverse import would be circular.
    """

    if relative_path.name in EXCLUDED_FILE_NAMES:
        return True

    if relative_path.suffix in EXCLUDED_SUFFIXES:
        return True

    return any(
        part in EXCLUDED_DIRECTORY_NAMES
        for part in relative_path.parts
    )
