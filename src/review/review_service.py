from __future__ import annotations

from src.review.change_snapshot import ChangeSnapshot
from src.review.review_report import ReviewReport


class ReviewService:
    """Turns a ChangeSnapshot into a ReviewReport.

    Pure/stateless on purpose: it does no I/O itself. Loading the
    snapshot (SnapshotRepository) and knowing the Run's current
    approve/reject decision (RunService) are the caller's job - this
    just does the ChangeSnapshot -> ReviewReport transformation, so it
    stays trivial to test and to later hand off to a Reviewer Agent
    that fills in `summary`/`risks` instead of leaving them empty.
    """

    def build_report(
        self,
        *,
        snapshot: ChangeSnapshot,
        approved: bool | None,
    ) -> ReviewReport:
        return ReviewReport(
            run_id=snapshot.run_id,
            summary=None,
            changed_files=snapshot.changed_files,
            risks=[],
            approved=approved,
        )
