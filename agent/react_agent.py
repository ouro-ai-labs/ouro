"""ReAct (Reasoning + Acting) agent implementation."""

import json
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from llm import LLMMessage
from tools.base import BaseTool
from utils import get_logger, terminal_ui

from .base import BaseAgent
from .composition import (
    CompositionPattern,
    CompositionPlan,
    CompositionResult,
    ExplorationAspect,
)
from .context import format_context_prompt
from .prompts import COMPOSITION_ASSESSMENT_PROMPT

if TYPE_CHECKING:
    from memory.graph import MemoryGraph, MemoryNode

    from .runtime import AgentRuntime

logger = get_logger(__name__)


class ReActAgent(BaseAgent):
    """Agent using ReAct (Reasoning + Acting) pattern.

    Can be used standalone or spawned by AgentRuntime for composable execution.
    When spawned by runtime, shares context through MemoryGraph.
    """

    def __init__(
        self,
        llm,
        tools: List[BaseTool],
        memory_node: Optional["MemoryNode"] = None,
        memory_graph: Optional["MemoryGraph"] = None,
    ):
        """Initialize ReActAgent.

        Args:
            llm: LLM instance
            tools: List of available tools
            memory_node: Optional MemoryNode for graph-backed context
            memory_graph: Optional MemoryGraph for cross-agent context sharing
        """
        super().__init__(llm, tools, memory_node=memory_node, memory_graph=memory_graph)

        # Runtime integration (set by AgentRuntime.spawn_agent)
        self._runtime: Optional["AgentRuntime"] = None
        self._depth: int = 0
        self._memory_node_id: Optional[str] = None

    SYSTEM_PROMPT = """<role>
You are a helpful AI assistant that uses tools to accomplish tasks efficiently and reliably.
</role>

<critical_rules>
IMPORTANT: Always think before acting
IMPORTANT: Use the most efficient tool for each operation
IMPORTANT: Manage todo lists for complex multi-step tasks
IMPORTANT: Mark tasks completed IMMEDIATELY after finishing them
</critical_rules>

<task_management>
Use the manage_todo_list tool for complex tasks to prevent forgetting steps.

WHEN TO USE TODO LISTS:
- Tasks with 3+ distinct steps
- Multi-file operations
- Complex workflows requiring planning
- Any task where tracking progress helps

TODO LIST RULES:
- Create todos BEFORE starting complex work
- Exactly ONE task must be in_progress at any time
- Mark tasks completed IMMEDIATELY after finishing
- Update status as you work through the list

<good_example>
User: Create a data pipeline that reads CSV, processes it, and generates report
Assistant: I'll use the todo list to track this multi-step task.
[Calls manage_todo_list with operation="add" for each step]
[Marks first task as in_progress before starting]
[Uses read_file tool]
[Marks as completed, moves to next task]
</good_example>

<bad_example>
User: Create a data pipeline that reads CSV, processes it, and generates report
Assistant: [Immediately starts without planning, forgets steps halfway through]
</bad_example>
</task_management>

<tool_usage_guidelines>
For file operations:
- Use glob_files to find files by pattern (fast, efficient)
- Use code_navigator to find function/class definitions (10x faster than grep, AST-based)
- Use grep_content for text search only (not for finding code structure)
- Use read_file only when you need full contents (avoid reading multiple large files at once)
- Use smart_edit for code edits (fuzzy match, auto backup, diff preview)
- Use edit_file for simple append/insert operations only
- Use write_file only for creating new files or complete rewrites

CRITICAL: Never read multiple large files in a single iteration - this causes context overflow!
Instead: Use code_navigator or grep_content to find specific information, then read only what you need.

For complex tasks:
- Use manage_todo_list to track progress
- Break into smaller, manageable steps
- Mark tasks completed as you go
- Keep exactly ONE task in_progress at a time

<good_example>
Task: Find all Python files that import 'requests'
Approach:
1. Use glob_files with pattern "**/*.py" to find Python files
2. Use grep_content with pattern "^import requests|^from requests" to search
Result: Efficient, minimal tokens used
</good_example>

<bad_example>
Task: Find all Python files that import 'requests'
Approach:
1. Use read_file on every Python file one by one
2. Manually search through content
Result: Wasteful, uses 100x more tokens
</bad_example>
</tool_usage_guidelines>

<workflow>
For each user request, follow this ReAct pattern:
1. THINK: Analyze what's needed, choose best tools
2. ACT: Execute with appropriate tools
3. OBSERVE: Check results and learn from them
4. REPEAT or COMPLETE: Continue the loop or provide final answer

When you have enough information, provide your final answer directly without using more tools.
</workflow>

<available_tools>
You have access to various tools including:
- Code navigation: code_navigator (find functions/classes/structure/usages)
- Code editing: smart_edit (intelligent edits with preview), edit_file
- File operations: glob_files, grep_content, read_file, write_file, search_files
- Git operations: git_status, git_diff, git_add, git_commit, git_log, git_branch, git_checkout, git_push, git_pull, git_remote, git_stash, git_clean
- Task management: manage_todo_list
- Utilities: calculate, web_search, shell

Always choose the most efficient tool for the task at hand.
</available_tools>

<delegation_strategy>
When running under AgentRuntime (compose mode), you can delegate subtasks to child agents.
Child agents share context through the memory graph.

Use delegation when:
- A subtask requires deep exploration (5+ iterations of searching/reading)
- Subtask details would clutter your context (e.g., exploring large codebases)
- You need to isolate experimental operations
- The subtask is self-contained and doesn't need frequent interaction

DO NOT delegate simple operations that can be done in 1-2 tool calls.
</delegation_strategy>"""

    async def run(self, task: str) -> str:
        """Execute ReAct loop until task is complete.

        Args:
            task: The task to complete

        Returns:
            Final answer as a string
        """
        # Build system message with context (only if not already in memory)
        # This allows multi-turn conversations to reuse the same system message
        if not self.memory.system_messages:
            system_content = self.SYSTEM_PROMPT
            try:
                context = await format_context_prompt()
                system_content = context + "\n" + system_content
            except Exception:
                # If context gathering fails, continue without it
                pass

            # Add system message only on first turn
            await self.memory.add_message(LLMMessage(role="system", content=system_content))

        # Add user task/message
        await self.memory.add_message(LLMMessage(role="user", content=task))

        tools = self.tool_executor.get_tool_schemas()

        # Use the generic ReAct loop implementation
        result = await self._react_loop(
            messages=[],  # Not used when use_memory=True
            tools=tools,
            use_memory=True,
            save_to_memory=True,
            task=task,
        )

        self._print_memory_stats()

        # Summarize for parent if this is a child agent
        if self._runtime and self._memory_node_id:
            await self.memory.summarize_for_parent(result)

        # Save memory state to database after task completion
        await self.memory.save_memory()

        return result

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        terminal_ui.print_memory_stats(stats)

    # ==========================================================================
    # Composition Methods (RFC-004)
    # ==========================================================================

    async def _assess_composition_need(self, task: str) -> CompositionPlan:
        """Assess whether a task needs composition (decomposition).

        Uses LLM to dynamically determine if the task should be broken down
        and what aspects need exploration.

        Args:
            task: The task to assess

        Returns:
            CompositionPlan indicating how to execute the task
        """
        import os

        # Build assessment prompt
        tool_names = [t.name for t in self.tool_executor.tools.values()]
        prompt = COMPOSITION_ASSESSMENT_PROMPT.format(
            task=task,
            working_directory=os.getcwd(),
            available_tools=", ".join(tool_names),
        )

        try:
            response = await self._call_llm(
                messages=[LLMMessage(role="user", content=prompt)],
                spinner_message="Assessing task complexity...",
            )

            result_text = self._extract_text(response)

            # Parse JSON response
            # Try to extract JSON from the response
            json_start = result_text.find("{")
            json_end = result_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = result_text[json_start:json_end]
                data = json.loads(json_str)

                if not data.get("should_compose", False):
                    return CompositionPlan.direct_execution()

                # Parse exploration aspects
                aspects = [
                    ExplorationAspect(
                        name=aspect_data.get("name", "unknown"),
                        description=aspect_data.get("description", ""),
                        focus_areas=aspect_data.get("focus_areas", []),
                    )
                    for aspect_data in data.get("exploration_aspects", [])
                ]

                pattern_str = data.get("pattern", "none")
                pattern = CompositionPattern(pattern_str)

                return CompositionPlan(
                    should_compose=True,
                    pattern=pattern,
                    exploration_aspects=aspects,
                    reasoning=data.get("reasoning", ""),
                )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse composition assessment: {e}")

        # Default to direct execution if assessment fails
        return CompositionPlan.direct_execution()

    async def delegate(
        self,
        subtask: str,
        inherit_context: bool = True,
        tool_filter: Optional[Set[str]] = None,
    ) -> str:
        """Delegate a subtask to a child agent via AgentRuntime.

        Requires this agent to be spawned by AgentRuntime. The child agent
        shares context through the MemoryGraph.

        Args:
            subtask: Description of the subtask
            inherit_context: Whether to inherit parent memory context
            tool_filter: Optional set of tool names to restrict

        Returns:
            Result of the subtask execution

        Raises:
            RuntimeError: If not running under AgentRuntime
        """
        logger.info(f"Delegating: {subtask[:100]}...")

        if not self._runtime or not self._memory_node_id:
            raise RuntimeError(
                "Cannot delegate without AgentRuntime. "
                "Use AgentRuntime.run() or run_with_composition() to enable delegation."
            )

        sub_agent = self._runtime.create_child_agent(
            parent_node_id=self._memory_node_id,
            task=subtask,
            tool_filter=tool_filter,
            scope="delegation",
            depth=self._depth + 1,
        )
        result = await sub_agent.run(subtask)

        # Summarize child's work for parent context
        await sub_agent.memory.summarize_for_parent(result)

        return f"Delegated task result:\n{result}"

    async def _execute_plan_pattern(
        self,
        task: str,
        plan: CompositionPlan,
    ) -> CompositionResult:
        """Execute the plan-execute composition pattern.

        This implements the four-phase execution:
        1. Explore: Parallel exploration of aspects
        2. Plan: Generate execution plan (handled by LLM)
        3. Execute: Execute using ReAct loop
        4. Synthesize: Return final result

        Args:
            task: The task to execute
            plan: The composition plan

        Returns:
            CompositionResult with execution details
        """
        import asyncio

        # Phase 1: Parallel exploration
        exploration_results: Dict[str, str] = {}

        if plan.exploration_aspects:
            terminal_ui.console.print(
                f"\n[bold blue]Exploring {len(plan.exploration_aspects)} aspects...[/bold blue]"
            )

            async def explore_aspect(aspect: ExplorationAspect) -> tuple:
                prompt = f"""Explore: {aspect.description}
Focus areas:
{chr(10).join(f'- {f}' for f in aspect.focus_areas)}

Use ONLY read-only tools. Report findings concisely."""

                try:
                    result = await self.delegate(
                        subtask=prompt,
                        inherit_context=True,
                        tool_filter={"glob_files", "grep_content", "read_file", "code_navigator"},
                    )
                    return (aspect.name, result)
                except Exception as e:
                    return (aspect.name, f"Exploration failed: {e}")

            # Run explorations
            tasks = [asyncio.create_task(explore_aspect(a)) for a in plan.exploration_aspects]
            gather_results = await asyncio.gather(*tasks, return_exceptions=True)

            for explore_result in gather_results:
                if isinstance(explore_result, tuple):
                    exploration_results[explore_result[0]] = explore_result[1]

            # Add exploration context to memory
            if exploration_results:
                context_msg = "[Exploration Results]\n" + "\n\n".join(
                    f"## {name}\n{result}" for name, result in exploration_results.items()
                )
                await self.memory.add_message(LLMMessage(role="user", content=context_msg))

        # Phase 2-4: Execute task with exploration context
        terminal_ui.console.print("\n[bold yellow]Executing task...[/bold yellow]")
        result = await self._react_loop(
            messages=[],
            tools=self.tool_executor.get_tool_schemas(),
            use_memory=True,
            save_to_memory=True,
            task=task,
        )

        return CompositionResult(
            success=True,
            final_answer=result,
            exploration_results=exploration_results,
        )

    async def run_with_composition(self, task: str) -> str:
        """Execute a task with automatic composition assessment.

        This is an alternative entry point that assesses whether the task
        needs composition before execution.

        Args:
            task: The task to execute

        Returns:
            Final answer as a string
        """
        # Assess composition need
        plan = await self._assess_composition_need(task)

        if not plan.should_compose:
            # Direct execution
            return await self.run(task)

        terminal_ui.console.print(
            f"\n[bold cyan]Using composition pattern: {plan.pattern.value}[/bold cyan]"
        )
        terminal_ui.console.print(f"[dim]Reasoning: {plan.reasoning}[/dim]")

        # Execute with composition
        if plan.pattern == CompositionPattern.PLAN_EXECUTE:
            result = await self._execute_plan_pattern(task, plan)
            return result.final_answer
        elif plan.pattern == CompositionPattern.PARALLEL_EXPLORE:
            result = await self._execute_plan_pattern(task, plan)  # Reuse pattern
            return result.final_answer
        else:
            # Fallback to direct execution
            return await self.run(task)
