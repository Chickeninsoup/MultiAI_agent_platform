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


def resolve_repository_write_path(
    repository_root: Path,
    requested_path: str,
) -> Path:
    root = repository_root.expanduser().resolve(strict=True)
    candidate = root / requested_path

    try:
        resolved_parent = candidate.parent.resolve(strict=True)
    except FileNotFoundError as error:
        raise PathNotFoundError(
            f"Parent directory does not exist: {requested_path}"
        ) from error

    if not resolved_parent.is_relative_to(root):
        raise PathSecurityError(
            f"Path escapes repository root: {requested_path}"
        )

    resolved_candidate = resolved_parent / candidate.name

    if resolved_candidate.exists():
        actual_target = resolved_candidate.resolve(strict=True)

        if not actual_target.is_relative_to(root):
            raise PathSecurityError(
                f"Path escapes repository root: {requested_path}"
            )

    return resolved_candidate