from __future__ import annotations

from enum import Enum


class ApprovalStatus(Enum):
    """Where an ApprovalRequest is in its lifecycle (5E-5D-1).

    Deliberately coarser than RuntimeApprovalRequest's status
    convention (a plain str: "pending"/"approved"/"rejected"). This
    model separates *whether* a request has been decided (PENDING vs
    RESOLVED, tracked here on ApprovalRequest) from *what* was decided
    (APPROVE/REJECT/MODIFY/CANCEL, tracked on the separate
    ApprovalResolution that resolves it). Collapsing both into one
    status field can't represent MODIFY/CANCEL without inventing more
    string states; keeping them apart lets ApprovalDecision grow
    without ApprovalStatus ever needing a third value.

    PENDING - no human decision has been recorded yet.

    RESOLVED - a human has recorded a terminal decision (see
    ApprovalResolution).
    """

    PENDING = "pending"
    RESOLVED = "resolved"
