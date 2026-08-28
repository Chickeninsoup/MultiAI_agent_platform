from __future__ import annotations

from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_parser import PlannerResponseParser
from src.planning.repair_planner import RepairPlanner
from src.planning.repair_prompt_builder import RepairPromptBuilder
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


class FakeProvider:
    def __init__(self) -> None:
        self.prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.prompt = prompt
        return '{"steps": []}'


def _repair_request() -> PlanRepairRequest:
    return PlanRepairRequest(
        original_plan=TaskPlan(task_id="task-1", steps=[]),
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-python",
                repairable=True,
            )
        ],
        instructions="Fix the validation errors and generate a new valid plan.",
    )


def test_repair_calls_provider() -> None:
    provider = FakeProvider()
    planner = RepairPlanner(
        provider, RepairPromptBuilder(), PlannerResponseParser()
    )

    planner.repair(_repair_request())

    assert provider.prompt is not None
    assert "failed validation" in provider.prompt


def test_repair_returns_planner_output_matching_existing_schema() -> None:
    provider = FakeProvider()
    planner = RepairPlanner(
        provider, RepairPromptBuilder(), PlannerResponseParser()
    )

    result = planner.repair(_repair_request())

    assert hasattr(result, "steps")
    assert result.steps == []


def test_repair_uses_default_prompt_builder_and_parser() -> None:
    provider = FakeProvider()
    planner = RepairPlanner(provider)

    result = planner.repair(_repair_request())

    assert hasattr(result, "steps")
