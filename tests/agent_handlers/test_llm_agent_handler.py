from dataclasses import dataclass

from src.agent_handlers.llm_agent_handler import LLMAgentHandler
from src.agent_message import AgentMessage


@dataclass
class _FakeTask:
    id: str


@dataclass
class _FakeRun:
    id: str


@dataclass
class _FakeResult:
    run_id: str
    status: str
    output_path: str


class FakeTaskService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_task_and_run(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeTask(id=kwargs["task_id"]), _FakeRun(id="run-001")


class FakeRunService:
    def __init__(self, result: _FakeResult | None = None) -> None:
        self.calls: list[str] = []
        self._result = result or _FakeResult(
            run_id="run-001",
            status="completed",
            output_path="tasks/task-1/runs/run-001/output.md",
        )

    def execute(self, task_id: str):
        self.calls.append(task_id)
        return self._result


def _message() -> AgentMessage:
    return AgentMessage(
        sender_id="manager",
        receiver_id="agent-coder",
        task_id="task-001",
        content="fix the bug",
        context={},
    )


def test_agent_id_returns_configured_id() -> None:
    handler = LLMAgentHandler(
        "agent-coder", FakeTaskService(), FakeRunService()
    )

    assert handler.agent_id == "agent-coder"


def test_handle_creates_task_and_run_from_message() -> None:
    task_service = FakeTaskService()
    run_service = FakeRunService()
    handler = LLMAgentHandler("agent-coder", task_service, run_service)

    handler.handle(_message())

    assert task_service.calls == [
        {
            "task_id": "task-001",
            "title": "fix the bug",
            "description": "fix the bug",
            "agent_id": "agent-coder",
            "input_text": "fix the bug",
            "created_by": "manager",
        }
    ]


def test_handle_executes_the_created_task() -> None:
    task_service = FakeTaskService()
    run_service = FakeRunService()
    handler = LLMAgentHandler("agent-coder", task_service, run_service)

    handler.handle(_message())

    assert run_service.calls == ["task-001"]


def test_handle_returns_summary_of_run_result() -> None:
    result = _FakeResult(
        run_id="run-001",
        status="completed",
        output_path="tasks/task-001/runs/run-001/output.md",
    )
    handler = LLMAgentHandler(
        "agent-coder", FakeTaskService(), FakeRunService(result)
    )

    response = handler.handle(_message())

    assert response == (
        "Run run-001 finished with status 'completed'. "
        "Output: tasks/task-001/runs/run-001/output.md"
    )
