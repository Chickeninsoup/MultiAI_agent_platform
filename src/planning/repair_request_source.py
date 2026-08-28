from __future__ import annotations

from enum import Enum


class RepairRequestSource(Enum):
    """Where a PlanRepairRequest came from (5E-5C-7A) - what wording
    RepairPromptBuilder should use, since "failed validation" is only
    true for one of these.

    VALIDATION - the plan was never executed; PlanValidator's static
    checks (UNKNOWN_AGENT, DEPENDENCY_CYCLE, ...) found a problem
    before anything ran.

    EXECUTION_FAILURE - the plan passed validation and started
    running; a step actually failed at runtime (RecoveryAction.
    REPAIR_PLAN, via FailureRepairRequestBuilder). Validation never
    failed here - execution did.
    """

    VALIDATION = "validation"
    EXECUTION_FAILURE = "execution_failure"
