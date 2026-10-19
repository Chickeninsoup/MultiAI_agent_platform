from typing import Protocol, runtime_checkable

from src.approval_application_outcome import ApprovalApplicationOutcome
from src.models import RunExecutionContext, RunExecutionResult
from src.run_continuation_checkpoint import RunContinuationCheckpoint


class RunExecutor(Protocol):
    """Execute one run using a prepared execution context."""

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        ...


@runtime_checkable
class ApprovalContinuationCapableExecutor(Protocol):
    """An additional, optional capability a RunExecutor may implement
    (5E-5D-6C) - deliberately a second, narrower Protocol rather than
    a new required method on RunExecutor itself: most RunExecutor
    implementations (SimulatedRunExecutor) have no concept of an
    approval pause to resume at all, and widening RunExecutor itself
    would force every implementation to grow a method it cannot
    sensibly perform.

    RunService.resume_after_approval() checks
    isinstance(executor, ApprovalContinuationCapableExecutor) before
    calling resume_after_approval() on it - @runtime_checkable makes
    that isinstance check valid (Protocol isinstance normally only
    works for data protocols without this decorator). An executor that
    does not implement this method fails that check, and
    RunService raises RunContinuationNotConfiguredError rather than
    silently falling back to a generic resume with approval gating
    disabled.
    """

    def resume_after_approval(
        self,
        context: RunExecutionContext,
        checkpoint: RunContinuationCheckpoint,
        outcome: ApprovalApplicationOutcome,
    ) -> RunExecutionResult:
        ...
