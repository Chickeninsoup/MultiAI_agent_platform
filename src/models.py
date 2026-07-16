from dataclasses import dataclass, field
from typing import Any


def require_non_empty_string(
    data: dict[str, Any],
    field_name: str,
    entity_name: str,
) -> str:
    value = data.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{entity_name} field '{field_name}' "
            "must be a non-empty string"
        )

    return value


def optional_string(
    data: dict[str, Any],
    field_name: str,
) -> str | None:
    value = data.get(field_name)

    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(
            f"Field '{field_name}' must be a string or null"
        )

    return value


def string_list(
    data: dict[str, Any],
    field_name: str,
) -> list[str]:
    value = data.get(field_name, [])

    if not isinstance(value, list):
        raise ValueError(
            f"Field '{field_name}' must be a list"
        )

    if not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"Field '{field_name}' must contain only strings"
        )

    return list(value)


@dataclass(frozen=True)
class AgentLimits:
    memory_mb: int
    cpus: int | float
    timeout_seconds: int
    max_input_tokens: int
    max_output_tokens: int

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "AgentLimits":
        required_fields = (
            "memory_mb",
            "cpus",
            "timeout_seconds",
            "max_input_tokens",
            "max_output_tokens",
        )

        for field_name in required_fields:
            if field_name not in data:
                raise ValueError(
                    f"Agent limits field '{field_name}' is required"
                )

        memory_mb = data["memory_mb"]
        cpus = data["cpus"]
        timeout_seconds = data["timeout_seconds"]
        max_input_tokens = data["max_input_tokens"]
        max_output_tokens = data["max_output_tokens"]

        if (
            not isinstance(memory_mb, int)
            or isinstance(memory_mb, bool)
            or memory_mb <= 0
        ):
            raise ValueError(
                "Agent limits field 'memory_mb' "
                "must be a positive integer"
            )

        if (
            not isinstance(cpus, (int, float))
            or isinstance(cpus, bool)
            or cpus <= 0
        ):
            raise ValueError(
                "Agent limits field 'cpus' "
                "must be a positive number"
            )

        integer_fields = {
            "timeout_seconds": timeout_seconds,
            "max_input_tokens": max_input_tokens,
            "max_output_tokens": max_output_tokens,
        }

        for field_name, value in integer_fields.items():
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(
                    f"Agent limits field '{field_name}' "
                    "must be a positive integer"
                )

        return cls(
            memory_mb=memory_mb,
            cpus=cpus,
            timeout_seconds=timeout_seconds,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
            "timeout_seconds": self.timeout_seconds,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    description: str
    owner: str
    status: str
    role: str
    default_model: str
    credential_id: str
    system_prompt_path: str
    tool_policy_path: str
    default_workspace_id: str
    capabilities: list[str]
    limits: AgentLimits
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "AgentDefinition":
        limits_data = data.get("limits")

        if not isinstance(limits_data, dict):
            raise ValueError(
                "Agent field 'limits' must be an object"
            )

        return cls(
            id=require_non_empty_string(data, "id", "Agent"),
            name=require_non_empty_string(data, "name", "Agent"),
            description=require_non_empty_string(
                data,
                "description",
                "Agent",
            ),
            owner=require_non_empty_string(data, "owner", "Agent"),
            status=require_non_empty_string(data, "status", "Agent"),
            role=require_non_empty_string(data, "role", "Agent"),
            default_model=require_non_empty_string(
                data,
                "default_model",
                "Agent",
            ),
            credential_id=require_non_empty_string(
                data,
                "credential_id",
                "Agent",
            ),
            system_prompt_path=require_non_empty_string(
                data,
                "system_prompt_path",
                "Agent",
            ),
            tool_policy_path=require_non_empty_string(
                data,
                "tool_policy_path",
                "Agent",
            ),
            default_workspace_id=require_non_empty_string(
                data,
                "default_workspace_id",
                "Agent",
            ),
            capabilities=string_list(data, "capabilities"),
            limits=AgentLimits.from_dict(limits_data),
            created_at=require_non_empty_string(
                data,
                "created_at",
                "Agent",
            ),
            updated_at=require_non_empty_string(
                data,
                "updated_at",
                "Agent",
            ),
        )

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "owner": self.owner,
            "status": self.status,
            "role": self.role,
            "default_model": self.default_model,
            "credential_id": self.credential_id,
            "system_prompt_path": self.system_prompt_path,
            "tool_policy_path": self.tool_policy_path,
            "default_workspace_id": self.default_workspace_id,
            "capabilities": list(self.capabilities),
            "limits": self.limits.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    title: str
    description: str
    workspace_id: str
    status: str
    priority: str
    created_by: str
    assigned_agents: list[str]
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    abandoned_at: str | None
    current_run_id: str | None
    run_count: int
    completion_criteria: list[str]
    tags: list[str]

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "TaskDefinition":
        run_count = data.get("run_count")

        if not isinstance(run_count, int) or run_count < 0:
            raise ValueError(
                "Task field 'run_count' "
                "must be a non-negative integer"
            )

        return cls(
            id=require_non_empty_string(data, "id", "Task"),
            title=require_non_empty_string(data, "title", "Task"),
            description=require_non_empty_string(
                data,
                "description",
                "Task",
            ),
            workspace_id=require_non_empty_string(
                data,
                "workspace_id",
                "Task",
            ),
            status=require_non_empty_string(data, "status", "Task"),
            priority=require_non_empty_string(
                data,
                "priority",
                "Task",
            ),
            created_by=require_non_empty_string(
                data,
                "created_by",
                "Task",
            ),
            assigned_agents=string_list(data, "assigned_agents"),
            created_at=require_non_empty_string(
                data,
                "created_at",
                "Task",
            ),
            updated_at=require_non_empty_string(
                data,
                "updated_at",
                "Task",
            ),
            started_at=optional_string(data, "started_at"),
            completed_at=optional_string(data, "completed_at"),
            abandoned_at=optional_string(data, "abandoned_at"),
            current_run_id=optional_string(data, "current_run_id"),
            run_count=run_count,
            completion_criteria=string_list(
                data,
                "completion_criteria",
            ),
            tags=string_list(data, "tags"),
        )

    def is_agent_assigned(self, agent_id: str) -> bool:
        return agent_id in self.assigned_agents

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "workspace_id": self.workspace_id,
            "status": self.status,
            "priority": self.priority,
            "created_by": self.created_by,
            "assigned_agents": list(self.assigned_agents),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "abandoned_at": self.abandoned_at,
            "current_run_id": self.current_run_id,
            "run_count": self.run_count,
            "completion_criteria": list(self.completion_criteria),
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class RunDefinition:
    id: str
    task_id: str
    agent_id: str
    status: str
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "RunDefinition":
        known_fields = {
            "id",
            "task_id",
            "agent_id",
            "status",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
        }

        metadata = {
            key: value
            for key, value in data.items()
            if key not in known_fields
        }

        return cls(
            id=require_non_empty_string(data, "id", "Run"),
            task_id=require_non_empty_string(
                data,
                "task_id",
                "Run",
            ),
            agent_id=require_non_empty_string(
                data,
                "agent_id",
                "Run",
            ),
            status=require_non_empty_string(data, "status", "Run"),
            created_at=require_non_empty_string(
                data,
                "created_at",
                "Run",
            ),
            updated_at=require_non_empty_string(
                data,
                "updated_at",
                "Run",
            ),
            started_at=optional_string(data, "started_at"),
            completed_at=optional_string(data, "completed_at"),
            metadata=metadata,
        )

    def is_completed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

        data.update(self.metadata)
        return data
