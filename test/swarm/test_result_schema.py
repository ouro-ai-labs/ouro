"""Tests for structured swarm task-result parsing."""

from __future__ import annotations

from ouro.capabilities.swarm.result_schema import coerce_task_result


def test_coerce_plain_text_result() -> None:
    result = coerce_task_result("Implemented the change")

    assert result.summary == "Implemented the change"
    assert result.followup_tasks == []


def test_coerce_json_result() -> None:
    raw = '{"summary": "Implemented the change", "artifacts": ["ouro/capabilities/swarm/coordinator.py"], "followup_tasks": [{"subject": "Add regression tests", "description": "Add missing test coverage", "activeForm": "Adding regression tests", "metadata": {"priority": "high"}}]}'
    result = coerce_task_result(raw)

    assert result.summary == "Implemented the change"
    assert result.artifacts == ["ouro/capabilities/swarm/coordinator.py"]
    assert result.followup_tasks == [
        {
            "subject": "Add regression tests",
            "description": "Add missing test coverage",
            "activeForm": "Adding regression tests",
            "metadata": {"priority": "high"},
        }
    ]


def test_coerce_json_embedded_in_text() -> None:
    raw = 'Done. {"summary": "Inspected the code", "outcome": "completed"}'
    result = coerce_task_result(raw)

    assert result.summary == "Inspected the code"
    assert result.outcome == "completed"
