from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewReport:
    run_id: str
    summary: str | None
    changed_files: list[str]
    risks: list[str]
    approved: bool | None
