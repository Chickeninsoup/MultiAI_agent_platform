from __future__ import annotations

import inspect

from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_output import PlannerOutput
from src.planning.runtime_plan_repair_service import (
    RuntimePlanRepairService,
)
from src.task_plan import TaskPlan


class FakeRepairPlanner:
    def __init__(self, output: PlannerOutput) -> None:
        self._output = output
        self.received_requests: list[PlanRepairRequest] = []

    def repair(self, repair_request: PlanRepairRequest) -> PlannerOutput:
        self.received_requests.append(repair_request)
        return self._output


def _request() -> PlanRepairRequest:
    return PlanRepairRequest(
        original_plan=TaskPlan(task_id="task-1", steps=[])
    )


def test_forwards_the_request_unchanged() -> None:
    repair_planner = FakeRepairPlanner(PlannerOutput())
    service = RuntimePlanRepairService(repair_planner)
    request = _request()

    service.repair(request)

    assert repair_planner.received_requests == [request]
    assert repair_planner.received_requests[0] is request


def test_returns_the_planner_output_unchanged() -> None:
    planner_output = PlannerOutput()
    repair_planner = FakeRepairPlanner(planner_output)
    service = RuntimePlanRepairService(repair_planner)

    result = service.repair(_request())

    assert result is planner_output


def test_repair_planner_is_a_required_dependency() -> None:
    signature = inspect.signature(RuntimePlanRepairService.__init__)
    repair_planner_param = signature.parameters["repair_planner"]

    assert repair_planner_param.default is inspect.Parameter.empty
