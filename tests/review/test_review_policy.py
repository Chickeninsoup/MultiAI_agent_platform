from src.review.change_snapshot import ChangeSnapshot
from src.review.review_policy import requires_review


def _snapshot(mutation_count: int) -> ChangeSnapshot:
    return ChangeSnapshot(
        run_id="run-001",
        changed_files=["src/main.py"] if mutation_count else [],
        mutation_count=mutation_count,
        test_results={},
        diff_path=None,
    )


def test_agent_coder_with_mutations_requires_review() -> None:
    assert (
        requires_review(
            agent_id="agent-coder",
            snapshot=_snapshot(1),
        )
        is True
    )


def test_agent_coder_without_mutations_does_not_require_review() -> None:
    assert (
        requires_review(
            agent_id="agent-coder",
            snapshot=_snapshot(0),
        )
        is False
    )


def test_agent_general_with_mutations_does_not_require_review() -> None:
    # Defensive: agent-general can't actually call write_file/patch_file
    # today (tool-policy.json disables them), so mutation_count should
    # never be nonzero for this agent — but the policy function itself
    # must not assume that, and should stay conservative either way.
    assert (
        requires_review(
            agent_id="agent-general",
            snapshot=_snapshot(1),
        )
        is False
    )
