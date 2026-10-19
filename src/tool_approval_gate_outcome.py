from __future__ import annotations

from enum import Enum


class ToolApprovalGateOutcome(Enum):
    """What the application should do right now, having asked
    ToolApprovalGate.check() about one ToolCall (5E-5D-4A).

    A third, distinct vocabulary from the two it sits between - not
    reused, on purpose:

    - ToolApprovalRequirement (src/tool_approval_requirement.py) is
      ToolApprovalPolicy's pure pre-execution *classification* of a
      ToolCall (does this kind of tool need approval at all).
    - ApprovalDecision (src/approval_decision.py) is the human's
      *later* response to a specific already-raised ApprovalRequest
      (APPROVE/REJECT/MODIFY/CANCEL).
    - ToolApprovalGateOutcome is neither - it's what the *caller*
      (whatever is about to dispatch a ToolCall) should do right now,
      having combined the policy classification with the side effect
      of actually raising an ApprovalRequest when one was required.
      "Policy says approval is required" and "an ApprovalRequest now
      exists and execution should pause" are different facts, at
      different points in time, told to different audiences - keeping
      three enums keeps a future runtime from having to guess which
      one governs an if/else it's writing.

    PROCEED - no ApprovalRequest was raised; the caller may continue
    toward normal tool execution and authorization exactly as if this
    gate did not exist.

    WAITING_FOR_APPROVAL - an ApprovalRequest now exists and is
    PENDING; the caller must not execute the ToolCall. What "must not
    execute" actually does at runtime (pausing a Run, a
    WAITING_FOR_APPROVAL RunStatus, resuming later) is deliberately
    not this stage's concern - see ToolApprovalGate's module docstring
    for the full list of what remains unwired.
    """

    PROCEED = "proceed"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
