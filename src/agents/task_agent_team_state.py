from enum import Enum


class TaskAgentTeamState(Enum):
    """The lifecycle state of a Task's assigned-agent team (5E-4B).

    Unassigned Tasks are implicitly OPEN - no explicit initialization
    needed at Task creation. The only legal forward transitions are
    OPEN -> LOCKED -> RELEASED; nothing moves backward (see
    TaskAgentTeamLifecycle).
    """

    OPEN = "open"
    LOCKED = "locked"
    RELEASED = "released"
