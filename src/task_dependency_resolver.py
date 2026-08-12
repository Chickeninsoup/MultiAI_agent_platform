from __future__ import annotations

from src.task_plan import TaskPlan, TaskStep


class CyclicDependencyError(ValueError):
    """Raised when a TaskPlan's depends_on graph contains a cycle."""


class TaskDependencyResolver:
    """Orders a TaskPlan's steps into rounds based on depends_on.

    Each round is a list of steps whose dependencies are all satisfied
    by earlier rounds - steps within a round have no dependency on one
    another, so they're the unit a future parallel scheduler (5D-4C/D)
    would dispatch together. This stage only computes the ordering; it
    does not execute anything or track step status.
    """

    def resolve(self, plan: TaskPlan) -> list[list[TaskStep]]:
        steps_by_id = {step.step_id: step for step in plan.steps}
        remaining_deps = {
            step.step_id: set(step.depends_on) for step in plan.steps
        }
        resolved_ids: set[str] = set()
        rounds: list[list[TaskStep]] = []

        while remaining_deps:
            ready_ids = [
                step_id
                for step_id, deps in remaining_deps.items()
                if deps <= resolved_ids
            ]

            if not ready_ids:
                raise CyclicDependencyError(
                    "cannot resolve depends_on for steps: "
                    f"{sorted(remaining_deps)}"
                )

            rounds.append([steps_by_id[step_id] for step_id in ready_ids])
            resolved_ids.update(ready_ids)
            for step_id in ready_ids:
                del remaining_deps[step_id]

        return rounds
