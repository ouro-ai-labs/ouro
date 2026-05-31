"""Tests for TaskAnalyzer."""

from __future__ import annotations

import pytest

from ouro.capabilities.swarm.analyzer import TaskAnalysis, TaskAnalyzer


class FakeLLM:
    """Fake LLM for testing TaskAnalyzer."""

    def __init__(self, response_text: str):
        self.response_text = response_text

    async def call_async(self, **kwargs):
        from ouro.core.llm import LLMResponse, StopReason

        return LLMResponse(
            content=self.response_text,
            stop_reason=StopReason.STOP,
        )

    def extract_text(self, response):
        return response.content


class TestTaskAnalyzer:
    async def test_simple_task_not_decomposed(self) -> None:
        response = '{"should_decompose": false, "complexity_score": 0.1, "reasoning": "Simple task", "subtasks": null}'
        analyzer = TaskAnalyzer(FakeLLM(response))
        analysis = await analyzer.analyze("Calculate 1+1")

        assert analysis.should_decompose is False
        assert analysis.complexity_score == 0.1
        assert analysis.subtasks is None

    async def test_complex_task_decomposed(self) -> None:
        response = '{"should_decompose": true, "complexity_score": 0.8, "reasoning": "Complex system", "subtasks": [{"subject": "Task 1", "description": "Desc 1"}]}'
        analyzer = TaskAnalyzer(FakeLLM(response))
        analysis = await analyzer.analyze("Build auth system")

        assert analysis.should_decompose is True
        assert analysis.complexity_score == 0.8
        assert len(analysis.subtasks) == 1

    async def test_should_use_swarm(self) -> None:
        response = '{"should_decompose": true, "complexity_score": 0.8, "reasoning": "Complex", "subtasks": []}'
        analyzer = TaskAnalyzer(FakeLLM(response))
        analysis = await analyzer.analyze("Build auth system")

        assert analyzer.should_use_swarm(analysis) is True

    async def test_should_not_use_swarm_low_score(self) -> None:
        response = '{"should_decompose": true, "complexity_score": 0.3, "reasoning": "Medium", "subtasks": []}'
        analyzer = TaskAnalyzer(FakeLLM(response))
        analysis = await analyzer.analyze("Medium task")

        assert analyzer.should_use_swarm(analysis) is False

    async def test_should_not_use_swarm_not_decomposable(self) -> None:
        response = '{"should_decompose": false, "complexity_score": 0.9, "reasoning": "Complex but atomic", "subtasks": null}'
        analyzer = TaskAnalyzer(FakeLLM(response))
        analysis = await analyzer.analyze("Atomic complex task")

        assert analyzer.should_use_swarm(analysis) is False

    async def test_malformed_response_fallback(self) -> None:
        response = "not valid json"
        analyzer = TaskAnalyzer(FakeLLM(response))
        analysis = await analyzer.analyze("Any task")

        assert analysis.should_decompose is False
        assert analysis.complexity_score == 0.5
