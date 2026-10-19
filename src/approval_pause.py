from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalPause:
    """Signals that a Run stopped before executing a ToolCall because
    ToolApprovalGate.check() returned WAITING_FOR_APPROVAL (5E-5D-4B).

    Carried on LLMRunResult.waiting_for_approval (default None, so
    every existing caller/test that never wired a ToolApprovalGate
    keeps getting exactly the same LLMRunResult shape as before) -
    deliberately its own minimal type rather than reusing
    ApprovalRequest directly: this is a runtime execution signal
    ("stop, and here are the three ids to report/route on"), not the
    domain/persistence record. ApprovalRequest already exists for
    that (reachable via ApprovalStore.get(approval_id) by whoever
    needs the full picture - proposed_action, reason, risk_level,
    input_preview). Keeping this flat and self-contained means it can
    never expose more than three identifiers, structurally - there is
    no ToolCall reference here to redact in the first place, not even
    one protected by field(repr=False).

    Clearly distinct from any FAILED/INTERRUPTED signal in this
    codebase (LLMRunLimitError - an exception; RunErrorCategory - a
    classification of a caught exception, src/run_errors.py) - this
    is not an error. Reaching a WAITING outcome never passes through
    classify_error()/RunErrorCategory at all: it's populated by a
    normal return from LLMRunExecutor.execute(), not raised, so it
    can never be misclassified as an execution failure by anything
    downstream that only ever sees caught exceptions.
    """

    approval_id: str
    run_id: str
    tool_call_id: str

    def __post_init__(self) -> None:
        for field_name in ("approval_id", "run_id", "tool_call_id"):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    f"ApprovalPause field '{field_name}' must be a "
                    "non-empty string"
                )
