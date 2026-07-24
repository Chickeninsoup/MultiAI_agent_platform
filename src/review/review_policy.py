from __future__ import annotations

from src.review.change_snapshot import ChangeSnapshot


def requires_review(
    *,
    agent_id: str,
    snapshot: ChangeSnapshot,
) -> bool:
    if agent_id != "agent-coder":
        return False

    return snapshot.mutation_count > 0
