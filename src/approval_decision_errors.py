class ApprovalRunNotFoundError(ValueError):
    pass


class ApprovalRunNotWaitingForApprovalError(ValueError):
    pass


class OrphanedApprovalRequestError(ValueError):
    pass


class ApprovalCheckpointMismatchError(ValueError):
    pass
