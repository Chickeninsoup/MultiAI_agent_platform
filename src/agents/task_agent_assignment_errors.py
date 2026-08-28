class TaskNotFoundForAssignmentError(ValueError):
    pass


class AgentNotFoundForAssignmentError(ValueError):
    pass


class AgentAlreadyAssignedToTaskError(ValueError):
    pass


class AgentAlreadyAssignedElsewhereError(ValueError):
    pass


class TaskAgentTeamLockedError(ValueError):
    pass


class TaskAgentTeamReleasedError(ValueError):
    pass
