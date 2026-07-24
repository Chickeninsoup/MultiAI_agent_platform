from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChangeSnapshot:
    run_id: str
    changed_files: list[str]
    mutation_count: int
    test_results: dict[str, Any]
    diff_path: str | None
