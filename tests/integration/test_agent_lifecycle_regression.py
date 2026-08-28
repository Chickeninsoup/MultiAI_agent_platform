"""5E-4E-3: Lifecycle Regression Verification.

Not a design stage - 5E-4A through 5E-4E-2 already decided the model
and froze it in docs/architecture/agent_lifecycle_policy.md. This
file exercises the full cross-stage chain (Template -> AgentDefinition
-> Task -> Assignment -> Lock -> Execute -> Complete/Fail -> Cleanup)
end to end, through the real production services, to prove future
changes to any one stage can't quietly break another.

"Execute" here is stood in by a hand-built PlanExecutionResult, same
as tests/integration/test_task_lifecycle_final_audit.py - actual
Planner/Executor wiring is exercised elsewhere; what this file checks
is what happens to Agent/Template/TaskAgent/Runtime state around that
boundary, not planning or execution itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.agent_registry import AgentRegistry
from src.agent_runtime_factory import AgentRuntimeFactory
from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import AgentTemplateRepository
from src.agents.task_agent_assignment_service import (
    TaskAgentAssignmentService,
)
from src.agents.task_agent_cleanup_service import TaskAgentCleanupService
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.agents.task_agent_team_state import TaskAgentTeamState
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_service import TaskCompletionService
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_service import TaskService


def _agent_dict(agent_id: str, template_id: str) -> dict[str, object]:
    return {
        "id": agent_id,
        "name": agent_id,
        "description": "An agent used for regression tests.",
        "owner": "owner-1",
        "status": "ready",
        "role": "engineer",
        "template_id": template_id,
        "default_model": "claude-model-placeholder",
        "credential_id": "cred-1",
        "system_prompt_path": "system-prompt.md",
        "tool_policy_path": "tool-policy.json",
        "default_workspace_id": "workspace-1",
        "capabilities": [],
        "limits": {
            "memory_mb": 512,
            "cpus": 1,
            "timeout_seconds": 60,
            "max_input_tokens": 50_000,
            "max_output_tokens": 10_000,
        },
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _write_agent(
    agents_dir: Path, agent_id: str, template_id: str
) -> None:
    agent_dir = agents_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.json").write_text(
        json.dumps(_agent_dict(agent_id, template_id)),
        encoding="utf-8",
    )


def _successful_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1", status=StepStatus.SUCCESS, output="done"
            )
        ]
    )


def _failed_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.FAILED,
                error="execution failed",
            )
        ]
    )


def _create_task(
    task_service: TaskService, task_id: str, agent_id: str
) -> None:
    task_service.create_task_and_run(
        task_id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        agent_id=agent_id,
        input_text="implement the feature",
        created_by="user-1",
    )


class _Rig:
    """Wires one full set of production services for these tests -
    everything Template/AgentDefinition/Task/Assignment/Execution/
    Cleanup touches, so each test only states the scenario, not the
    plumbing."""

    def __init__(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        self.agents_dir = agents_dir
        self.agent_registry = AgentRegistry(AgentRepository(agents_dir))
        self.templates = AgentTemplateRepository()

        self.task_repository = TaskRepository(tmp_path)
        self.run_repository = RunRepository(tmp_path)
        self.task_service = TaskService(
            task_repository=self.task_repository,
            run_repository=self.run_repository,
        )

        self.task_agent_registry = TaskAgentRegistry()
        self.team_lifecycle = TaskAgentTeamLifecycle(
            self.task_agent_registry
        )
        self.assignment_service = TaskAgentAssignmentService(
            self.agent_registry,
            self.task_agent_registry,
            self.task_repository,
            self.team_lifecycle,
        )
        self.completion_service = TaskCompletionService(
            self.task_repository
        )
        self.cleanup_service = TaskAgentCleanupService(
            self.task_repository,
            self.task_agent_registry,
            self.team_lifecycle,
        )
        # task_service/run_service below are never invoked by
        # create_handlers() - it only reads TaskAgentRegistry.
        self.runtime_factory = AgentRuntimeFactory(
            self.agent_registry,
            self.task_agent_registry,
            task_service=object(),
            run_service=object(),
        )

    def add_agent(self, agent_id: str, template_id: str) -> None:
        _write_agent(self.agents_dir, agent_id, template_id)

    def add_template(self, template_id: str, name: str) -> None:
        self.templates.save(
            AgentTemplate(template_id=template_id, name=name)
        )


def test_full_happy_path_clears_task_state_but_keeps_reusable_assets(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path)
    rig.add_agent("agent-a", "backend-template")
    rig.add_template("backend-template", "Backend Developer")
    _create_task(rig.task_service, "task-a", "agent-a")

    rig.assignment_service.assign("task-a", "agent-a", "backend-template")

    # --- Plan (implicit: TaskPlanningContextFactory would join
    # TaskAgentRegistry + AgentTemplateRepository here) / Execute ---
    handlers_during_execution = rig.runtime_factory.create_handlers(
        "task-a"
    )
    assert len(handlers_during_execution) == 1

    rig.team_lifecycle.lock("task-a")
    completed = rig.completion_service.complete_if_successful(
        "task-a", _successful_result()
    )
    assert completed is True
    assert rig.cleanup_service.cleanup("task-a") is True

    task = rig.task_repository.load("task-a")
    assert task.status == "completed"
    assert task.completed_at is not None

    # --- TaskAgent membership: gone ---
    assert rig.task_agent_registry.list_agents("task-a") == []
    assert rig.task_agent_registry.owner_task_id("agent-a") is None
    assert rig.team_lifecycle.state("task-a") is TaskAgentTeamState.RELEASED

    # --- Reusable assets: untouched ---
    assert rig.agent_registry.get_agent("agent-a").id == "agent-a"
    assert rig.templates.get("backend-template") is not None

    # --- Runtime: gone once the team is released ---
    assert rig.runtime_factory.create_handlers("task-a") == []


def test_failed_execution_preserves_task_agent_definition_and_template(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path)
    rig.add_agent("agent-a", "backend-template")
    rig.add_template("backend-template", "Backend Developer")
    _create_task(rig.task_service, "task-a", "agent-a")

    task_agent = rig.assignment_service.assign(
        "task-a", "agent-a", "backend-template"
    )
    rig.team_lifecycle.lock("task-a")

    completed = rig.completion_service.complete_if_successful(
        "task-a", _failed_result()
    )
    assert completed is False

    task = rig.task_repository.load("task-a")
    assert task.status == "in_progress"
    assert task.completed_at is None

    # --- Nothing was released: TaskAgent, AgentDefinition, Template
    # and the runtime it can still build all survive a failed run ---
    assert rig.task_agent_registry.list_agents("task-a") == [task_agent]
    assert rig.task_agent_registry.owner_task_id("agent-a") == "task-a"
    assert rig.team_lifecycle.state("task-a") is TaskAgentTeamState.LOCKED
    assert rig.agent_registry.get_agent("agent-a").id == "agent-a"
    assert rig.templates.get("backend-template") is not None
    assert len(rig.runtime_factory.create_handlers("task-a")) == 1


def test_task_isolation_across_full_lifecycle(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.add_agent("agent-a", "backend-template")
    rig.add_agent("agent-b", "reviewer-template")
    rig.add_template("backend-template", "Backend Developer")
    rig.add_template("reviewer-template", "Security Reviewer")
    _create_task(rig.task_service, "task-a", "agent-a")
    _create_task(rig.task_service, "task-b", "agent-b")

    rig.assignment_service.assign("task-a", "agent-a", "backend-template")
    task_agent_b = rig.assignment_service.assign(
        "task-b", "agent-b", "reviewer-template"
    )
    rig.team_lifecycle.lock("task-a")
    rig.team_lifecycle.lock("task-b")

    completed = rig.completion_service.complete_if_successful(
        "task-a", _successful_result()
    )
    assert completed is True
    assert rig.cleanup_service.cleanup("task-a") is True

    # --- Task A: fully released ---
    assert rig.task_repository.load("task-a").status == "completed"
    assert rig.task_agent_registry.list_agents("task-a") == []
    assert rig.task_agent_registry.owner_task_id("agent-a") is None
    assert rig.team_lifecycle.state("task-a") is TaskAgentTeamState.RELEASED
    assert rig.runtime_factory.create_handlers("task-a") == []

    # --- Task B: completely unaffected by Task A's completion/cleanup ---
    assert rig.task_repository.load("task-b").status == "in_progress"
    assert rig.task_agent_registry.list_agents("task-b") == [task_agent_b]
    assert rig.task_agent_registry.owner_task_id("agent-b") == "task-b"
    assert rig.team_lifecycle.state("task-b") is TaskAgentTeamState.LOCKED
    assert len(rig.runtime_factory.create_handlers("task-b")) == 1

    # --- Reusable assets for both agents/templates: untouched ---
    assert rig.agent_registry.get_agent("agent-a").id == "agent-a"
    assert rig.agent_registry.get_agent("agent-b").id == "agent-b"
    assert rig.templates.get("backend-template") is not None
    assert rig.templates.get("reviewer-template") is not None
