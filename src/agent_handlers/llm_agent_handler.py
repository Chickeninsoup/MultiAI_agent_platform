from __future__ import annotations

from src.agent_message import AgentMessage
from src.run_service import RunService
from src.task_service import TaskService


class LLMAgentHandler:
    """Wires an AgentMessage into the Task/Run pipeline.

    The bridge between MessageRouter (who's reachable right now) and
    TaskService/RunService (how work actually gets created and
    executed). One Task/Run is created per message, using the
    message's own task_id rather than generating one, so a sender can
    address a follow-up message at the same task_id it already knows.
    """

    def __init__(
        self,
        agent_id: str,
        task_service: TaskService,
        run_service: RunService,
    ) -> None:
        self._agent_id = agent_id
        self._task_service = task_service
        self._run_service = run_service

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        task, _run = self._task_service.create_task_and_run(
            task_id=message.task_id,
            title=message.content,
            description=message.content,
            agent_id=self._agent_id,
            input_text=message.content,
            created_by=message.sender_id,
        )

        result = self._run_service.execute(task.id)

        return (
            f"Run {result.run_id} finished with status "
            f"'{result.status}'. Output: {result.output_path}"
        )
