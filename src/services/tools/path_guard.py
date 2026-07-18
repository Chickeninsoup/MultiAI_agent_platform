from pathlib import Path


class PathSecurityError(Exception):
    error_code = "PATH_OUTSIDE_REPOSITORY"


class PathNotFoundError(Exception):
    error_code = "PATH_NOT_FOUND"


def resolve_repository_path(
    repository_root: Path,
    requested_path: str,
) -> Path:
    root = repository_root.expanduser().resolve(strict=True)
    candidate = root / requested_path

    try:
        resolved_candidate = candidate.expanduser().resolve(strict=True)
    except FileNotFoundError as error:
        raise PathNotFoundError(
            f"Path does not exist: {requested_path}"
        ) from error

    if not resolved_candidate.is_relative_to(root):
        raise PathSecurityError(
            f"Path escapes repository root: {requested_path}"
        )

    return resolved_candidate