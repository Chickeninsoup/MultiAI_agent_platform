from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextFile:
    """One file a ContextSelector chose to include, and why.

    Just "path + reason" for now (5D-6B-1) - no token size, source, or
    importance score yet, since nothing consumes those. A future
    ContextSelector (5D-6B-2) and per-request budget (5D-6B-3) can add
    fields here once there's an actual reader for them, rather than
    guessing at a shape now.
    """

    path: str
    reason: str
