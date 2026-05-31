"""Task complexity analyzer for auto-swarm decision.

Determines whether a user task should be decomposed into sub-tasks
and executed by multiple agents in parallel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ouro.core.llm import LLMMessage, LLMResponse, StopReason
from ouro.core.log import get_logger

logger = get_logger(__name__)


@dataclass
class TaskAnalysis:
    """Result of analyzing a task for swarm suitability."""

    should_decompose: bool
    complexity_score: float  # 0.0 - 1.0
    reasoning: str
    subtasks: list[dict[str, Any]] | None = None


COMPLEXITY_ANALYSIS_PROMPT = """You are a task analyzer. Your job is to determine if a user request is complex enough to benefit from parallel execution by multiple agents.

Analyze the following task and respond with a JSON object:

```json
{
  "should_decompose": true/false,
  "complexity_score": 0.0-1.0,
  "reasoning": "Brief explanation of why this task should or should not be decomposed",
  "subtasks": [
    {
      "subject": "Short imperative title",
      "description": "Detailed description of what this subtask involves",
      "activeForm": "Present continuous form (optional)"
    }
  ]
}
```

Guidelines:
- should_decompose: true if the task has 3+ independent steps, touches multiple files/modules, or requires different skills (research + coding + testing)
- complexity_score: 0.0 (trivial, single step) to 1.0 (very complex, multi-domain)
- subtasks: Only include if should_decompose is true. Each subtask should be independently executable.

Examples:

Task: "Calculate 1+1"
Response: {"should_decompose": false, "complexity_score": 0.0, "reasoning": "Single arithmetic operation", "subtasks": null}

Task: "Implement a complete user authentication system with login, registration, password reset, and email verification"
Response: {"should_decompose": true, "complexity_score": 0.9, "reasoning": "Multi-component system with independent modules", "subtasks": [{"subject": "Design database schema for users", "description": "Create tables for users, sessions, password resets with proper indexes"}, {"subject": "Implement registration API", "description": "Build signup endpoint with validation and password hashing"}, {"subject": "Implement login API", "description": "Build login endpoint with JWT token generation"}, {"subject": "Implement password reset flow", "description": "Build forgot password and reset endpoints with email tokens"}, {"subject": "Implement email verification", "description": "Build email verification system with token generation"}]}

Task: "Fix the bug where users can't login"
Response: {"should_decompose": false, "complexity_score": 0.3, "reasoning": "Likely a single bug fix, though investigation may be needed", "subtasks": null}

Task: "{task}"
Response:"""


class TaskAnalyzer:
    """Analyzes tasks to determine if they should be decomposed for swarm execution."""

    def __init__(self, llm, complexity_threshold: float = 0.6):
        self.llm = llm
        self.complexity_threshold = complexity_threshold

    async def analyze(self, task: str) -> TaskAnalysis:
        """Analyze a task and return decomposition recommendation."""
        prompt = COMPLEXITY_ANALYSIS_PROMPT.replace("{task}", task)

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self.llm.call_async(
            messages=messages,
            max_tokens=2000,
        )

        try:
            content = self.llm.extract_text(response)
            # Extract JSON from the response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                logger.warning("TaskAnalyzer: No JSON found in response, using default")
                return TaskAnalysis(
                    should_decompose=False,
                    complexity_score=0.5,
                    reasoning="Failed to parse analysis, falling back to single-agent",
                )

            json_str = content[json_start:json_end]
            result = json.loads(json_str)

            return TaskAnalysis(
                should_decompose=result.get("should_decompose", False),
                complexity_score=result.get("complexity_score", 0.5),
                reasoning=result.get("reasoning", "No reasoning provided"),
                subtasks=result.get("subtasks"),
            )

        except Exception as e:
            logger.warning(f"TaskAnalyzer: Failed to parse response: {e}")
            return TaskAnalysis(
                should_decompose=False,
                complexity_score=0.5,
                reasoning=f"Analysis failed: {e}",
            )

    def should_use_swarm(self, analysis: TaskAnalysis) -> bool:
        """Determine if swarm should be used based on analysis."""
        return analysis.should_decompose and analysis.complexity_score >= self.complexity_threshold
