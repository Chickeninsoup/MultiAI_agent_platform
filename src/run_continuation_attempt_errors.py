class RunContinuationError(RuntimeError):
    """Base for every error raised while coordinating or driving one
    resume_after_approval() attempt (5E-5D-6C) - a RuntimeError
    family, matching ApprovalApplicationError's own reasoning: none of
    these describe bad caller input (run_id/approval_id are already
    validated by ApprovalContinuationPreparationService), they
    describe the system refusing to proceed, or proceeding and hitting
    an uncertain state."""

    pass


class RunContinuationNotConfiguredError(RunContinuationError):
    """resume_after_approval() was called without every required
    collaborator wired (the continuation preparation service, the
    application service, the attempt repository, or an executor that
    actually implements approval-aware continuation). Raised instead
    of silently falling back to a generic resume or an ungated
    executor."""

    pass


class RunContinuationMismatchError(RunContinuationError):
    """The requested approval_id does not match what this Run's
    continuation is actually about - either a fresh preparation's own
    approval_id disagreeing with the caller's request, or a completed
    attempt record's stored source approval_id disagreeing with it.
    Raised before any claim is attempted, or before a cached result is
    returned - a retry for one approval must never silently resume or
    report on a different one."""

    pass


class RunContinuationBlockedError(RunContinuationError):
    """A RunContinuationAttemptRecord already exists for this run_id
    but has no completed transition yet
    (RunContinuationAttemptStatus.CLAIMED). Raised regardless of which
    approval_id the caller asked about - an incomplete attempt blocks
    *all* automatic continuation of this Run, whether it reflects an
    active owner or an interrupted earlier attempt; this service
    cannot and does not try to tell those apart."""

    pass


class RunContinuationFailedError(RunContinuationError):
    """Driving the continuation (applying the pending decision,
    running the remaining tool/LLM loop, or finalizing the Run's new
    terminal/paused state) raised unexpectedly. The attempt claim is
    preserved; nothing here retries automatically."""

    pass


class RunContinuationPersistenceError(RunContinuationError):
    """The continuation was driven to a transition, but persisting
    that transition on the attempt record failed. The claim is
    preserved. The Run itself may already reflect its new terminal/
    paused state on disk by this point (see the service's own
    docstring for write ordering) - this error specifically means the
    *attempt record* could not be marked COMPLETED to match, so a
    retry must not be allowed to run automatically."""

    pass
