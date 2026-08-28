from __future__ import annotations

import pytest

from src.planning.plan_repair_loop import PlanRepairLoop
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.plan_schema import PlannedStep
from src.planning.plan_validation import PlanValidationResult
from src.planning.planner_output import PlannerOutput
from src.planning.planning_errors import PlanRepairLimitExceeded
from src.planning.repair_decision_service import RepairDecisionService
from src.planning.repair_preparation_service import (
    RepairPreparationService,
)
from src.planning.repair_request_builder import RepairRequestBuilder
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan, TaskStep


class FakePlanner:
    def __init__(self, plan: TaskPlan) -> None:
        self.plan = plan
        self.calls = 0

    def create_plan(self, request, task_id, context=None) -> TaskPlan:
        self.calls += 1
        return self.plan


class FakeValidator:
    def __init__(self, results: list[PlanValidationResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def validate(self, plan: TaskPlan) -> PlanValidationResult:
        self.calls += 1
        return self._results.pop(0)


class FakeRepairPlanner:
    def __init__(self, output: PlannerOutput) -> None:
        self.output = output
        self.calls = 0
        self.received_contexts: list = []

    def repair(self, request: PlanRepairRequest) -> PlannerOutput:
        self.calls += 1
        self.received_contexts.append(request.context)
        return self.output


def _valid_result() -> PlanValidationResult:
    return PlanValidationResult(valid=True)


def _invalid_result() -> PlanValidationResult:
    return PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-python",
                repairable=True,
            )
        ],
    )


def _preparation_service() -> RepairPreparationService:
    return RepairPreparationService(
        decision_service=RepairDecisionService(),
        builder=RepairRequestBuilder(),
    )


def test_returns_immediately_when_first_plan_is_valid() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    planner = FakePlanner(plan)
    repair_planner = FakeRepairPlanner(PlannerOutput())
    validator = FakeValidator([_valid_result()])
    loop = PlanRepairLoop(
        planner, repair_planner, validator, _preparation_service()
    )

    result = loop.run("do something", "task-1")

    assert result.plan is plan
    assert result.attempts == 1
    assert result.repaired is False
    assert repair_planner.calls == 0


def test_repairs_once_then_succeeds() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    planner = FakePlanner(plan)
    repaired_output = PlannerOutput(
        steps=[
            PlannedStep(
                step_id="s1",
                agent_id="agent-coder",
                description="fixed",
            )
        ]
    )
    repair_planner = FakeRepairPlanner(repaired_output)
    validator = FakeValidator([_invalid_result(), _valid_result()])
    loop = PlanRepairLoop(
        planner, repair_planner, validator, _preparation_service()
    )

    result = loop.run("do something", "task-1")

    assert result.attempts == 2
    assert result.repaired is True
    assert repair_planner.calls == 1
    assert result.plan.steps == [
        TaskStep(
            step_id="s1", agent_id="agent-coder", description="fixed"
        )
    ]


def test_raises_when_repair_limit_exceeded() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    planner = FakePlanner(plan)
    repair_planner = FakeRepairPlanner(PlannerOutput())
    validator = FakeValidator(
        [_invalid_result(), _invalid_result(), _invalid_result()]
    )
    loop = PlanRepairLoop(
        planner,
        repair_planner,
        validator,
        _preparation_service(),
        max_attempts=3,
    )

    with pytest.raises(PlanRepairLimitExceeded):
        loop.run("do something", "task-1")

    assert repair_planner.calls == 2


def test_same_context_is_threaded_through_every_repair_attempt() -> (
    None
):
    plan = TaskPlan(task_id="task-1", steps=[])
    planner = FakePlanner(plan)
    repair_planner = FakeRepairPlanner(PlannerOutput())
    validator = FakeValidator(
        [_invalid_result(), _invalid_result(), _invalid_result()]
    )
    loop = PlanRepairLoop(
        planner,
        repair_planner,
        validator,
        _preparation_service(),
        max_attempts=3,
    )
    context = TaskPlanningContext(task_id="task-1", available_agents=[])

    with pytest.raises(PlanRepairLimitExceeded):
        loop.run("do something", "task-1", context)

    assert repair_planner.received_contexts == [context, context]
    assert all(c is context for c in repair_planner.received_contexts)


def test_raises_immediately_when_errors_not_repairable() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    planner = FakePlanner(plan)
    repair_planner = FakeRepairPlanner(PlannerOutput())
    fatal_result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="EMPTY_TASK",
                message="Task has no description",
                repairable=False,
            )
        ],
    )
    validator = FakeValidator([fatal_result])
    loop = PlanRepairLoop(
        planner, repair_planner, validator, _preparation_service()
    )

    with pytest.raises(PlanRepairLimitExceeded):
        loop.run("do something", "task-1")

    assert repair_planner.calls == 0
