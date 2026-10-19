class ApprovalApplicationError(RuntimeError):
    """Base for every error ApprovalApplicationService.apply() raises
    (5E-5D-6B) - a RuntimeError family, not ValueError like most of
    this codebase's domain models, because none of these describe bad
    caller input: apply()'s only inputs are three identifiers, already
    validated by ApprovalContinuationPreparationService if they are
    wrong. Every error below instead describes the *system* refusing
    to safely proceed - a blocked, uncertain, or inconsistent state
    discovered at or after claim acquisition - which this codebase's
    RunErrorCategory/LLMRunLimitError precedent (also RuntimeError)
    already treats as a different kind of failure than a rejected
    argument."""

    pass


class ApprovalApplicationMismatchError(ApprovalApplicationError):
    """The approval_id/task_id/run_id/pending_tool_call_id/decision/
    effective-input binding a caller or a persisted claim carries does
    not agree with freshly validated preparation. Raised before any
    dispatch - a mismatch here must prevent execution, never trigger
    it with stale or substituted data."""

    pass


class ApprovalApplicationBlockedError(ApprovalApplicationError):
    """An ApprovalApplicationRecord already exists for this approval_id
    but has no completed outcome yet (ApprovalApplicationStatus.CLAIMED).
    Raised instead of dispatching again - this may mean another process
    is actively applying this decision right now, or that a previous
    attempt crashed after claiming but before finishing. apply() cannot
    tell those apart and does not try to; both require the same refusal
    to auto-redispatch, and resolving which one actually happened is a
    manual reconciliation step outside this service."""

    pass


class ApprovalApplicationDispatchError(ApprovalApplicationError):
    """Dispatching the resolved pending call raised an exception that
    ToolExecutor.execute() itself did not already convert into a
    failure ToolResult (ToolExecutor normally catches handler
    exceptions internally - see its own _execute()). Reaching this
    error means something failed outside that normal path. The claim
    remains CLAIMED; nothing here retries automatically."""

    pass


class ApprovalApplicationPersistenceError(ApprovalApplicationError):
    """Dispatch produced an outcome, but persisting it as COMPLETED
    failed. The claim remains CLAIMED (whatever was on disk before this
    attempt, untouched - JsonRepository.save()'s tmp-file-then-replace
    means a failed write never leaves a half-written COMPLETED record
    in its place). A side effect may already have happened and be
    unrecorded; this is the specific, named case where "the tool may
    have already run, and this service cannot prove whether it has
    retried safely" must be surfaced rather than silently swallowed or
    silently retried."""

    pass
