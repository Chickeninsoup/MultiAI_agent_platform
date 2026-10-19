class DuplicateApprovalRequestError(ValueError):
    pass


class ApprovalRequestNotFoundError(ValueError):
    pass


class ApprovalAlreadyResolvedError(ValueError):
    pass


class MismatchedApprovalResolutionError(ValueError):
    pass


class InvalidApprovalIdError(ValueError):
    pass
