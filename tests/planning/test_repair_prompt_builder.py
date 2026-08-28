from __future__ import annotations

from src.agents.task_agent_info import TaskAgentInfo
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.repair_prompt_builder import RepairPromptBuilder
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


def _request(
    *, context: TaskPlanningContext | None = None
) -> PlanRepairRequest:
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
        context=context,
    )


def test_prompt_contains_errors() -> None:
    builder = RepairPromptBuilder()

    prompt = builder.build(_request())

    assert "UNKNOWN_AGENT" in prompt.content
    assert "Unknown agent: agent-python" in prompt.content


def test_prompt_contains_instruction() -> None:
    builder = RepairPromptBuilder()

    prompt = builder.build(_request())

    assert "generate a new valid plan" in prompt.content


def test_prompt_contains_agents() -> None:
    builder = RepairPromptBuilder()
    request_with_context = _request(
        context=TaskPlanningContext(
            task_id="task-1",
            available_agents=[
                TaskAgentInfo(agent_id="agent-coder", role="Coder"),
                TaskAgentInfo(
                    agent_id="agent-reviewer", role="Reviewer"
                ),
            ],
        )
    )

    prompt = builder.build(request_with_context)

    assert "agent-coder" in prompt.content
    assert "agent-reviewer" in prompt.content


def test_prompt_requires_json_output() -> None:
    builder = RepairPromptBuilder()

    prompt = builder.build(_request())

    assert "JSON" in prompt.content


def test_prompt_restricts_repair_to_task_agents() -> None:
    builder = RepairPromptBuilder()
    request_with_context = _request(
        context=TaskPlanningContext(
            task_id="task-1",
            available_agents=[
                TaskAgentInfo(agent_id="agent-a", role="Coder")
            ],
        )
    )

    prompt = builder.build(request_with_context)

    assert "ONLY agents" in prompt.content
    assert "Do NOT invent agent IDs" in prompt.content


def test_prompt_explicitly_handles_no_task_agents() -> None:
    builder = RepairPromptBuilder()
    request_with_context = _request(
        context=TaskPlanningContext(
            task_id="task-1", available_agents=[]
        )
    )

    prompt = builder.build(request_with_context)

    assert "No agents are currently assigned" in prompt.content


def test_validation_source_keeps_validation_wording() -> None:
    builder = RepairPromptBuilder()

    prompt = builder.build(_request())

    assert "Your generated plan failed validation." in prompt.content


def test_execution_failure_source_uses_execution_wording() -> None:
    builder = RepairPromptBuilder()
    request = PlanRepairRequest(
        original_plan=TaskPlan(task_id="task-1", steps=[]),
        errors=[
            ValidationError(
                code="EXECUTION_FAILURE",
                message="Execution failed on step 'step-1': timeout",
                repairable=True,
            )
        ],
        instructions=(
            "Fix the step that failed during execution "
            "and generate a new valid plan."
        ),
        source=RepairRequestSource.EXECUTION_FAILURE,
    )

    prompt = builder.build(request)

    assert (
        "Your generated plan encountered an execution failure."
        in prompt.content
    )
    assert "Your generated plan failed validation." not in prompt.content
