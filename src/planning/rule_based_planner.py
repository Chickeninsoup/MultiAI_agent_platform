from __future__ import annotations

from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan, TaskStep


class RuleBasedPlanner:
    """Default Planner: keyword rules pick a fixed plan shape.

    No NLP, no priority scheme beyond "first matching rule wins" - a
    request matching multiple rules (e.g. mentioning both "research"
    and "review") just takes whichever branch is checked first. That's
    fine for 5D-5B-1: the point is proving Planner can produce
    different TaskPlan shapes (including multi-step plans with
    depends_on), not building a real classifier. A future
    ClaudePlanner replaces this branching entirely rather than this
    growing more elif branches.

    Plans below can name agent-researcher / agent-reviewer, which may
    not exist in the AgentRegistry yet - deliberately not this
    Planner's concern. Whether a planned agent_id is real belongs to
    5D-5C Plan Validation.

    Accepts (and ignores) context (5E-1B, retyped to
    TaskPlanningContext in Phase 1C-3A) purely so the Planner
    Protocol's extended signature doesn't break this default
    implementation - keyword rules don't need available_agents or
    constraints to pick a plan shape.
    """

    def create_plan(
        self,
        request: str,
        task_id: str,
        context: TaskPlanningContext | None = None,
    ) -> TaskPlan:
        normalized_request = request.lower()

        if "research" in normalized_request and (
            "implement" in normalized_request
            or "code" in normalized_request
        ):
            return self._create_research_and_code_plan(
                request=request, task_id=task_id
            )

        if "review" in normalized_request:
            return self._create_review_plan(
                request=request, task_id=task_id
            )

        return self._create_coding_plan(
            request=request, task_id=task_id
        )

    @staticmethod
    def _create_coding_plan(
        *, request: str, task_id: str
    ) -> TaskPlan:
        return TaskPlan(
            task_id=task_id,
            steps=[
                TaskStep(
                    step_id="coding",
                    agent_id="agent-coder",
                    description=request,
                )
            ],
        )

    @staticmethod
    def _create_research_and_code_plan(
        *, request: str, task_id: str
    ) -> TaskPlan:
        return TaskPlan(
            task_id=task_id,
            steps=[
                TaskStep(
                    step_id="research",
                    agent_id="agent-researcher",
                    description=(
                        "Research the task and identify relevant "
                        f"approaches and constraints: {request}"
                    ),
                ),
                TaskStep(
                    step_id="coding",
                    agent_id="agent-coder",
                    description=(
                        "Implement the requested work using the "
                        f"research findings: {request}"
                    ),
                    depends_on=["research"],
                ),
            ],
        )

    @staticmethod
    def _create_review_plan(
        *, request: str, task_id: str
    ) -> TaskPlan:
        return TaskPlan(
            task_id=task_id,
            steps=[
                TaskStep(
                    step_id="review",
                    agent_id="agent-reviewer",
                    description=request,
                )
            ],
        )
