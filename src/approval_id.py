from __future__ import annotations

import re

from src.approval_errors import InvalidApprovalIdError

_APPROVAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
"""ASCII letters, digits, hyphen, underscore only, 1-128 characters.

No existing identifier/path-segment validator was found anywhere in
this codebase to reuse (5E-5D-4A-1 audit finding - TaskRepository/
RunRepository/PlanRepository/etc. all build tasks_dir/<id>/... paths
directly from a caller-supplied id with no validation at all; this is
a pre-existing, codebase-wide gap, not one unique to approvals). This
pattern is the conservative allow-list this stage's task explicitly
asks for as the fallback when no existing validator exists: it
structurally cannot match "." or "..", any path separator ("/" or
"\\"), an absolute path, a control character, or a whitespace-only
value, because none of those characters are in the allowed set - so
there is nothing to special-case reject, only one allow-list to
satisfy.
"""


def validate_approval_id(approval_id: str) -> None:
    """The one shared boundary every approval-related repository path
    construction must call before turning approval_id into a
    filesystem path (5E-5D-4A-1).

    Deliberately narrow: this only answers "is this string safe to
    use as a single path segment," not whether the approval it names
    actually exists (ApprovalRequestNotFoundError, a completely
    separate concern raised by ApprovalStore, one layer up). Called
    from ApprovalRequestRepository.get_approval_dir() and
    ApprovalResolutionRepository.get_resolution_file() - the single
    choke point each repository already funnels every path-building
    method through (save/load/exists for the former, save/get for the
    latter) - so create(), get(), and resolve() on ApprovalStore are
    all covered by validating in exactly two places, not by scattering
    checks across every call site individually.

    Raises before anything touches the filesystem: this function does
    no I/O itself, and every caller invokes it before the first
    Path.exists()/mkdir()/open() of the operation it's guarding, so a
    rejected id causes zero filesystem mutation - not even a directory
    is created.

    Deliberately does not attempt to "fix" an invalid id into a safe
    one (e.g. stripping ".." or replacing separators) - a caller that
    supplied "../outside" almost certainly has a bug (or worse) worth
    surfacing loudly via InvalidApprovalIdError, not silently working
    around by handing back a different, unrelated approval_id under a
    sanitized name.
    """

    if not _APPROVAL_ID_PATTERN.fullmatch(approval_id):
        raise InvalidApprovalIdError(
            f"Invalid approval_id: {approval_id!r}"
        )
