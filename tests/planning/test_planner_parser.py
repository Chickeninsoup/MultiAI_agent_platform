from __future__ import annotations

import json

import pytest

from src.planning.planner_parser import PlannerResponseParser


def test_parse_valid_response() -> None:
    raw = json.dumps(
        {
            "steps": [
                {
                    "step_id": "research",
                    "agent_id": "agent-researcher",
                    "description": "research problem",
                    "depends_on": [],
                }
            ]
        }
    )

    result = PlannerResponseParser().parse(raw)

    assert len(result.steps) == 1
    assert result.steps[0].agent_id == "agent-researcher"


def test_missing_field_raises_key_error() -> None:
    raw = json.dumps({"steps": [{"step_id": "a"}]})

    with pytest.raises(KeyError):
        PlannerResponseParser().parse(raw)


def test_invalid_json_raises() -> None:
    with pytest.raises(Exception):
        PlannerResponseParser().parse("invalid")


def test_missing_dependency_defaults_empty() -> None:
    raw = json.dumps(
        {
            "steps": [
                {
                    "step_id": "a",
                    "agent_id": "coder",
                    "description": "code",
                }
            ]
        }
    )

    result = PlannerResponseParser().parse(raw)

    assert result.steps[0].depends_on == []


def test_parses_multiple_steps_with_dependencies() -> None:
    raw = json.dumps(
        {
            "steps": [
                {
                    "step_id": "research",
                    "agent_id": "agent-researcher",
                    "description": "research",
                    "depends_on": [],
                },
                {
                    "step_id": "coding",
                    "agent_id": "agent-coder",
                    "description": "implement",
                    "depends_on": ["research"],
                },
            ]
        }
    )

    result = PlannerResponseParser().parse(raw)

    assert len(result.steps) == 2
    assert result.steps[1].depends_on == ["research"]


def test_missing_steps_key_raises_key_error() -> None:
    with pytest.raises(KeyError):
        PlannerResponseParser().parse(json.dumps({}))
