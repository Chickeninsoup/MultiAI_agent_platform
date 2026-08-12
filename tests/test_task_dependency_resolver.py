from __future__ import annotations

import pytest

from src.task_dependency_resolver import (
    CyclicDependencyError,
    TaskDependencyResolver,
)
from src.task_plan import TaskPlan, TaskStep


def test_resolve_returns_empty_list_for_empty_plan() -> None:
    resolver = TaskDependencyResolver()
    plan = TaskPlan(task_id="task-001", steps=[])

    assert resolver.resolve(plan) == []


def test_resolve_puts_independent_steps_in_a_single_round() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-coder", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-coder", description="do b"
    )
    resolver = TaskDependencyResolver()
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    assert resolver.resolve(plan) == [[step_a, step_b]]


def test_resolve_orders_a_linear_chain_into_sequential_rounds() -> None:
    research = TaskStep(
        step_id="research",
        agent_id="agent-researcher",
        description="find API documentation",
    )
    coding = TaskStep(
        step_id="coding",
        agent_id="agent-coder",
        description="implement API",
        depends_on=["research"],
    )
    review = TaskStep(
        step_id="review",
        agent_id="agent-reviewer",
        description="review code",
        depends_on=["coding"],
    )
    resolver = TaskDependencyResolver()
    plan = TaskPlan(
        task_id="task-001", steps=[research, coding, review]
    )

    assert resolver.resolve(plan) == [[research], [coding], [review]]


def test_resolve_groups_a_diamond_dependency_by_round() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-coder", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-coder", description="do b"
    )
    step_c = TaskStep(
        step_id="c",
        agent_id="agent-coder",
        description="do c",
        depends_on=["a", "b"],
    )
    resolver = TaskDependencyResolver()
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b, step_c])

    assert resolver.resolve(plan) == [[step_a, step_b], [step_c]]


def test_resolve_raises_on_a_direct_cycle() -> None:
    step_a = TaskStep(
        step_id="a",
        agent_id="agent-coder",
        description="do a",
        depends_on=["b"],
    )
    step_b = TaskStep(
        step_id="b",
        agent_id="agent-coder",
        description="do b",
        depends_on=["a"],
    )
    resolver = TaskDependencyResolver()
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    with pytest.raises(CyclicDependencyError):
        resolver.resolve(plan)


def test_resolve_raises_on_a_self_dependency() -> None:
    step_a = TaskStep(
        step_id="a",
        agent_id="agent-coder",
        description="do a",
        depends_on=["a"],
    )
    resolver = TaskDependencyResolver()
    plan = TaskPlan(task_id="task-001", steps=[step_a])

    with pytest.raises(CyclicDependencyError):
        resolver.resolve(plan)


def test_cyclic_dependency_error_is_a_value_error() -> None:
    assert issubclass(CyclicDependencyError, ValueError)
