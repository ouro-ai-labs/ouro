"""Task complexity analyzer for deciding whether to use swarm execution.

The analyzer only answers whether a task is complex enough to benefit
from Task V2-backed swarm orchestration. It does not decompose the task.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ouro.core.llm import LLMMessage
from ouro.core.log import get_logger

logger = get_logger(__name__)


@dataclass
class TaskAnalysis:
    """Result of analyzing a task for swarm suitability."""

    should_use_swarm: bool
    complexity_score: float  # 0.0 - 1.0
    reasoning: str


COMPLEXITY_ANALYSIS_PROMPT = """You are a task analyzer. Your job is to determine if a user request is complex enough to benefit from Task V2-backed swarm execution.

Analyze the following task and respond with a JSON object:

```json
{
  "should_use_swarm": true/false,
  "complexity_score": 0.0-1.0,
  "reasoning": "Brief explanation of why this task should or should not use swarm execution"
}
```

Guidelines:
- should_use_swarm: true if the task likely requires multiple dependent steps, coordination across files/modules, or distinct phases such as investigation, implementation, and verification
- complexity_score: 0.0 (trivial, single step) to 1.0 (very complex, multi-domain)
- Do not decompose the task. Do not return subtasks.

Examples:

Task: "Calculate 1+1"
Response: {"should_use_swarm": false, "complexity_score": 0.0, "reasoning": "Single arithmetic operation"}

Task: "Implement a complete user authentication system with login, registration, password reset, and email verification"
Response: {"should_use_swarm": true, "complexity_score": 0.9, "reasoning": "Large multi-phase task with implementation and verification dependencies"}

Task: "Fix the bug where users can't login"
Response: {"should_use_swarm": false, "complexity_score": 0.3, "reasoning": "Likely a focused bug fix that should start with a single investigator"}

Task: "{task}"
Response:"""


class TaskAnalyzer:
    """Analyze tasks to determine if they should use swarm execution."""

    def __init__(self, llm, complexity_threshold: float = 0.6):
        self.llm = llm
        self.complexity_threshold = complexity_threshold

    async def analyze(self, task: str) -> TaskAnalysis:
        """Analyze a task and return a swarm-routing recommendation."""
        prompt = COMPLEXITY_ANALYSIS_PROMPT.replace("{task}", task)

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self.llm.call_async(
            messages=messages,
            max_tokens=1000,
        )

        try:
            content = self.llm.extract_text(response)
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                logger.warning("TaskAnalyzer: No JSON found in response, using default")
                return TaskAnalysis(
                    should_use_swarm=False,
                    complexity_score=0.5,
                    reasoning="Failed to parse analysis, falling back to single-agent",
                )

            result = json.loads(content[json_start:json_end])

            return TaskAnalysis(
                should_use_swarm=result.get("should_use_swarm", False),
                complexity_score=result.get("complexity_score", 0.5),
                reasoning=result.get("reasoning", "No reasoning provided"),
            )

        except Exception as e:
            logger.warning(f"TaskAnalyzer: Failed to parse response: {e}")
            return TaskAnalysis(
                should_use_swarm=False,
                complexity_score=0.5,
                reasoning=f"Analysis failed: {e}",
            )

    def should_use_swarm(self, analysis: TaskAnalysis) -> bool:
        """Determine if swarm should be used based on analysis."""
        return analysis.should_use_swarm and analysis.complexity_score >= self.complexity_threshold
