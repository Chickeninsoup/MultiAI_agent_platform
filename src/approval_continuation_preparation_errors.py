class ApprovalResolutionPendingError(ValueError):
    """Raised by ApprovalContinuationPreparationService.prepare() when
    the approval referenced by a paused Run's checkpoint has no
    recorded ApprovalResolution yet (5E-5D-6A) - the explicit
    not-ready error this stage's task framing requires, distinct from
    every other failure here (those describe inconsistent or missing
    *records*; this one describes a record set that is entirely
    consistent but simply not yet decided)."""

    pass
