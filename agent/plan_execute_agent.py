"""Enhanced Plan-and-Execute agent with exploration, parallel execution, and adaptive replanning."""

import asyncio
import re
from typing import Dict, List, Optional, Tuple

from llm import LLMMessage
from memory.scope import MemoryScope, ScopedMemoryView
from utils import get_logger, terminal_ui

from .base import BaseAgent
from .context import format_context_prompt
from .plan_types import (
    ExecutionPlan,
    ExplorationResult,
    PlanStep,
    ReplanRequest,
    ReplanTrigger,
    StepStatus,
)
from .prompts import (
    EXECUTOR_PROMPT,
    EXPLORER_PROMPT,
    PLANNER_PROMPT,
    REPLANNER_PROMPT,
    SYNTHESIZER_PROMPT,
)

logger = get_logger(__name__)


class PlanExecuteAgent(BaseAgent):
    """Four-phase Plan-Execute agent with exploration and parallel execution.

    Phases:
    1. EXPLORE: Gather context through parallel exploration agents
    2. PLAN: Create dependency-aware plan informed by exploration
    3. EXECUTE: Execute steps with parallel batching and adaptive replanning
    4. SYNTHESIZE: Combine results into final answer
    """

    # Configuration
    MAX_EXPLORATION_AGENTS = 3
    MAX_PARALLEL_STEPS = 4
    REPLAN_THRESHOLD = 2

    # Read-only tools for exploration phase
    EXPLORATION_TOOLS = {"glob_files", "grep_content", "read_file", "code_navigator"}

    def __init__(self, *args, **kwargs):
        """Initialize the enhanced plan-execute agent."""
        super().__init__(*args, **kwargs)
        self._exploration_results: Optional[ExplorationResult] = None
        self._current_plan: Optional[ExecutionPlan] = None
        self._failure_count = 0

    async def run(self, task: str) -> str:
        """Execute the four-phase agent loop.

        Args:
            task: The task to complete

        Returns:
            Final answer as a string
        """
        # Initialize global memory scope
        global_scope = ScopedMemoryView(self.memory, MemoryScope.GLOBAL)

        # Phase 1: EXPLORE
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold blue]PHASE 1: EXPLORATION[/bold blue]", style="blue")
        self._exploration_results = await self._explore(task, global_scope)
        terminal_ui.console.print()
        terminal_ui.console.print(
            f"[dim]Exploration complete. Discovered {len(self._exploration_results.discovered_files)} files, "
            f"{len(self._exploration_results.constraints)} constraints.[/dim]"
        )

        # Phase 2: PLAN
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold cyan]PHASE 2: PLANNING[/bold cyan]", style="cyan")
        self._current_plan = await self._create_plan(task, self._exploration_results)
        terminal_ui.console.print()
        terminal_ui.console.print(self._format_plan(self._current_plan), style="dim")

        # Phase 3: EXECUTE (with potential replanning)
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold yellow]PHASE 3: EXECUTION[/bold yellow]", style="yellow")
        step_results = await self._execute_plan(self._current_plan, global_scope)

        # Phase 4: SYNTHESIZE
        terminal_ui.console.print()
        terminal_ui.console.rule("[bold green]PHASE 4: SYNTHESIS[/bold green]", style="green")
        final_answer = await self._synthesize(task, step_results, global_scope)

        # Commit exploration summary to global memory for persistence
        global_scope.set_summary(self._exploration_results.context_summary)
        await global_scope.commit_to_global()

        # Print memory statistics
        self._print_memory_stats()

        # Save memory state
        self.memory.save_memory()

        return final_answer

    # ==================== PHASE 1: EXPLORATION ====================

    async def _explore(self, task: str, global_scope: ScopedMemoryView) -> ExplorationResult:
        """Run parallel exploration to gather context.

        Args:
            task: The main task to explore for
            global_scope: The global memory scope

        Returns:
            ExplorationResult with discovered context
        """
        exploration_scope = ScopedMemoryView(
            self.memory, MemoryScope.EXPLORATION, parent_view=global_scope
        )

        # Define exploration aspects
        exploration_tasks = [
            ("file_structure", "Discover relevant files and directory structure"),
            ("code_patterns", "Identify relevant code patterns, APIs, and dependencies"),
            ("constraints", "Identify constraints, requirements, and potential blockers"),
        ]

        terminal_ui.console.print(
            f"[dim]Running {len(exploration_tasks)} parallel explorations...[/dim]"
        )

        # Run explorations in parallel
        try:
            results = await self._run_parallel_explorations(exploration_tasks, task)
        except Exception as e:
            logger.warning(f"Parallel exploration failed, falling back to sequential: {e}")
            results = await self._run_sequential_explorations(exploration_tasks, task)

        # Combine results
        combined = ExplorationResult(
            discovered_files=self._extract_files(results),
            code_patterns=results.get("code_patterns", {}),
            constraints=self._extract_constraints(results),
            recommendations=self._generate_recommendations(results),
            context_summary=self._summarize_exploration(results),
        )

        # Save exploration summary to scope
        exploration_scope.add_message(
            LLMMessage(
                role="assistant",
                content=f"[Exploration Complete]\n{combined.context_summary}",
            )
        )
        exploration_scope.set_summary(combined.context_summary)

        return combined

    async def _run_parallel_explorations(
        self, tasks: List[Tuple[str, str]], main_task: str
    ) -> Dict[str, dict]:
        """Run multiple exploration tasks in parallel.

        Args:
            tasks: List of (aspect, description) tuples
            main_task: The main task being explored

        Returns:
            Dict mapping aspect names to exploration results
        """

        async def run_exploration(aspect: str, description: str) -> Tuple[str, dict]:
            try:
                result = await self._run_single_exploration(aspect, description, main_task)
                return aspect, result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Exploration {aspect} failed: {e}")
                return aspect, {"error": str(e)}

        tasks_list = []
        async with asyncio.TaskGroup() as tg:
            for aspect, description in tasks:
                tasks_list.append(tg.create_task(run_exploration(aspect, description)))

        results: Dict[str, dict] = {}
        for task in tasks_list:
            aspect, result = task.result()
            results[aspect] = result

        return results

    async def _run_sequential_explorations(
        self, tasks: List[Tuple[str, str]], main_task: str
    ) -> Dict[str, dict]:
        """Run explorations sequentially (fallback if parallel fails).

        Args:
            tasks: List of (aspect, description) tuples
            main_task: The main task being explored

        Returns:
            Dict mapping aspect names to exploration results
        """
        results = {}
        for aspect, description in tasks:
            try:
                result = await self._run_single_exploration(aspect, description, main_task)
                results[aspect] = result
            except Exception as e:
                logger.warning(f"Exploration {aspect} failed: {e}")
                results[aspect] = {"error": str(e)}
        return results

    async def _run_single_exploration(self, aspect: str, description: str, main_task: str) -> dict:
        """Run a single exploration using isolated mini-loop.

        Args:
            aspect: The aspect being explored
            description: Description of the exploration focus
            main_task: The main task context

        Returns:
            Dict with exploration findings
        """
        terminal_ui.console.print(f"[dim]  Exploring: {aspect}...[/dim]")

        # Use only read-only tools for exploration
        all_tools = self.tool_executor.get_tool_schemas()
        exploration_tools = [
            t for t in all_tools if t.get("function", {}).get("name") in self.EXPLORATION_TOOLS
        ]

        # Build exploration prompt
        prompt = EXPLORER_PROMPT.format(aspect=aspect, description=description, task=main_task)

        messages = [LLMMessage(role="user", content=prompt)]

        # Run exploration in isolated context
        result = await self._react_loop(
            messages=messages,
            tools=exploration_tools,
            max_iterations=self.max_iterations,
            use_memory=False,
            save_to_memory=False,
            verbose=False,
        )

        return {"aspect": aspect, "findings": result}

    def _extract_files(self, results: Dict[str, dict]) -> List[str]:
        """Extract discovered file paths from exploration results."""
        files = []
        for aspect, data in results.items():
            if isinstance(data, dict) and "findings" in data:
                # Simple extraction - look for file paths in findings
                findings = data["findings"]
                # Match common file path patterns
                file_matches = re.findall(r"[\w./\\-]+\.\w+", findings)
                files.extend(f for f in file_matches if "/" in f or "\\" in f)
        return list(set(files))[:20]  # Dedupe and limit

    def _extract_constraints(self, results: Dict[str, dict]) -> List[str]:
        """Extract constraints from exploration results."""
        constraints = []
        constraint_data = results.get("constraints", {})
        if isinstance(constraint_data, dict) and "findings" in constraint_data:
            # Extract constraint-like statements
            findings = constraint_data["findings"]
            lines = findings.split("\n")
            for line in lines:
                line = line.strip()
                if line and any(
                    kw in line.lower()
                    for kw in ["must", "cannot", "should", "require", "need", "limit"]
                ):
                    constraints.append(line[:200])  # Limit length
        return constraints[:10]  # Limit count

    def _generate_recommendations(self, results: Dict[str, dict]) -> List[str]:
        """Generate recommendations based on exploration results."""
        recommendations = []
        if results.get("constraints", {}).get("findings"):
            recommendations.append("Consider constraints before planning")
        if results.get("code_patterns", {}).get("findings"):
            recommendations.append("Follow existing code patterns")
        return recommendations

    def _summarize_exploration(self, results: Dict[str, dict]) -> str:
        """Summarize all exploration results."""
        parts = []
        for aspect, data in results.items():
            if isinstance(data, dict) and "findings" in data:
                findings = data["findings"]
                truncated = findings[:500] + "..." if len(findings) > 500 else findings
                parts.append(f"**{aspect}**:\n{truncated}")
        return "\n\n".join(parts) if parts else "No exploration findings."

    # ==================== PHASE 2: PLANNING ====================

    async def _create_plan(self, task: str, exploration: ExplorationResult) -> ExecutionPlan:
        """Create structured plan informed by exploration results.

        Args:
            task: The task to plan
            exploration: Results from exploration phase

        Returns:
            ExecutionPlan with steps and dependencies
        """
        # Build system context
        system_content = "You are a planning expert. Create clear, dependency-aware plans."
        try:
            context = await asyncio.to_thread(format_context_prompt)
            system_content = context + "\n" + system_content
        except Exception:
            pass

        # Build planner prompt
        prompt = PLANNER_PROMPT.format(
            task=task,
            exploration_context=exploration.context_summary,
            constraints="\n".join(exploration.constraints) or "None identified",
        )

        messages = [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=prompt),
        ]

        response = await self._call_llm(messages=messages)

        # Track token usage
        if response.usage:
            self.memory.token_tracker.add_input_tokens(response.usage.get("input_tokens", 0))
            self.memory.token_tracker.add_output_tokens(response.usage.get("output_tokens", 0))

        plan_text = self._extract_text(response)

        # Parse plan into structured format
        plan = self._parse_plan(task, plan_text, exploration)

        # Save plan to memory
        await self.memory.add_message(
            LLMMessage(
                role="assistant",
                content=f"[Plan Created - v{plan.version}]\n{self._format_plan(plan)}",
            )
        )

        return plan

    def _parse_plan(
        self, task: str, plan_text: str, exploration: ExplorationResult
    ) -> ExecutionPlan:
        """Parse LLM plan output into structured ExecutionPlan.

        Args:
            task: The original task
            plan_text: Raw plan text from LLM
            exploration: Exploration context

        Returns:
            Structured ExecutionPlan
        """
        steps = []
        parallel_groups: List[List[str]] = []

        lines = plan_text.strip().split("\n")
        for line in lines:
            # Match numbered steps
            match = re.match(r"^\d+[\.)]\s+(.+)$", line.strip())
            if match:
                step_desc = match.group(1)
                step_id = f"step_{len(steps) + 1}"

                # Extract dependencies
                depends_on: List[str] = []
                dep_match = re.search(r"\[depends:\s*([^\]]+)\]", step_desc, re.IGNORECASE)
                if dep_match:
                    deps = dep_match.group(1).strip()
                    if deps.lower() != "none":
                        depends_on = [f"step_{d.strip()}" for d in deps.split(",")]
                    step_desc = re.sub(
                        r"\[depends:[^\]]+\]", "", step_desc, flags=re.IGNORECASE
                    ).strip()

                # Extract parallel hints
                parallel_match = re.search(r"\[parallel:\s*([^\]]+)\]", step_desc, re.IGNORECASE)
                if parallel_match:
                    parallel_ids = [f"step_{p.strip()}" for p in parallel_match.group(1).split(",")]
                    parallel_ids.append(step_id)
                    # Find or create parallel group
                    found = False
                    for group in parallel_groups:
                        if any(pid in group for pid in parallel_ids):
                            group.extend([p for p in parallel_ids if p not in group])
                            found = True
                            break
                    if not found:
                        parallel_groups.append(parallel_ids)
                    step_desc = re.sub(
                        r"\[parallel:[^\]]+\]", "", step_desc, flags=re.IGNORECASE
                    ).strip()

                # Remove [completed] marker if present
                step_desc = re.sub(r"\[completed\]", "", step_desc, flags=re.IGNORECASE).strip()

                steps.append(
                    PlanStep(
                        id=step_id,
                        description=step_desc,
                        depends_on=depends_on,
                    )
                )

        return ExecutionPlan(
            task=task,
            steps=steps,
            parallel_groups=parallel_groups,
            exploration_context=exploration,
        )

    def _format_plan(self, plan: ExecutionPlan) -> str:
        """Format plan for display.

        Args:
            plan: The plan to format

        Returns:
            Formatted string representation
        """
        lines = [f"Task: {plan.task}", f"Version: {plan.version}", "Steps:"]
        status_icons = {
            StepStatus.PENDING: "[ ]",
            StepStatus.IN_PROGRESS: "[~]",
            StepStatus.COMPLETED: "[x]",
            StepStatus.FAILED: "[!]",
            StepStatus.SKIPPED: "[-]",
        }
        for step in plan.steps:
            icon = status_icons.get(step.status, "[ ]")
            deps = f" (depends: {', '.join(step.depends_on)})" if step.depends_on else ""
            lines.append(f"  {icon} {step.id}: {step.description}{deps}")

        if plan.parallel_groups:
            lines.append("Parallel Groups:")
            for i, group in enumerate(plan.parallel_groups, 1):
                lines.append(f"  Group {i}: {', '.join(group)}")

        return "\n".join(lines)

    # ==================== PHASE 3: EXECUTION ====================

    async def _execute_plan(self, plan: ExecutionPlan, global_scope: ScopedMemoryView) -> List[str]:
        """Execute plan with parallel steps and adaptive replanning.

        Args:
            plan: The plan to execute
            global_scope: Global memory scope

        Returns:
            List of step result strings
        """
        execution_scope = ScopedMemoryView(
            self.memory, MemoryScope.EXECUTION, parent_view=global_scope
        )

        step_results = []
        self._failure_count = 0

        while True:
            # Get next batch of executable steps
            batch = plan.get_parallel_batch()
            if not batch:
                # Check if all done or blocked
                if plan.all_completed():
                    break
                if plan.has_failed_steps():
                    terminal_ui.console.print(
                        "[yellow]Some steps failed. Checking for replan...[/yellow]"
                    )
                    if self._should_replan(plan):
                        request = self._create_replan_request(plan)
                        plan = await self._replan(plan, request)
                        self._failure_count = 0
                        continue
                break

            # Execute batch
            total_steps = len(plan.steps)
            completed_count = sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)

            if len(batch) == 1:
                # Single step execution
                step = batch[0]
                terminal_ui.console.print()
                terminal_ui.console.print(
                    f"[bold magenta]Step {completed_count + 1}/{total_steps}:[/bold magenta] "
                    f"[white]{step.description}[/white]"
                )
                result = await self._execute_step(step, plan, execution_scope)
                step_results.append(result)
            else:
                # Parallel step execution
                terminal_ui.console.print()
                terminal_ui.console.print(
                    f"[bold magenta]Executing {len(batch)} steps in parallel[/bold magenta]"
                )
                for step in batch:
                    terminal_ui.console.print(f"  [dim]- {step.description}[/dim]")

                try:
                    results = await self._execute_parallel_steps(batch, plan, execution_scope)
                    step_results.extend(results)
                except Exception as e:
                    logger.warning(f"Parallel execution failed: {e}")
                    # Fall back to sequential
                    for step in batch:
                        result = await self._execute_step(step, plan, execution_scope)
                        step_results.append(result)

            # Check for replan triggers
            if self._should_replan(plan):
                request = self._create_replan_request(plan)
                plan = await self._replan(plan, request)
                self._failure_count = 0

        return step_results

    async def _execute_step(
        self, step: PlanStep, plan: ExecutionPlan, execution_scope: ScopedMemoryView
    ) -> str:
        """Execute a single step with full context.

        Args:
            step: The step to execute
            plan: The current plan
            execution_scope: Execution memory scope

        Returns:
            Step result string
        """
        step.status = StepStatus.IN_PROGRESS

        # Build context from exploration and previous steps
        history = self._build_step_context(step, plan)
        exploration_context = ""
        if plan.exploration_context:
            exploration_context = plan.exploration_context.context_summary

        # Build executor prompt
        prompt = EXECUTOR_PROMPT.format(
            step_num=step.id,
            step=step.description,
            exploration_context=exploration_context,
            history=history,
        )

        messages = [LLMMessage(role="user", content=prompt)]
        tools = self.tool_executor.get_tool_schemas()

        try:
            result = await self._react_loop(
                messages=messages,
                tools=tools,
                max_iterations=self.max_iterations,
                use_memory=False,
                save_to_memory=False,
                verbose=True,
            )

            step.status = StepStatus.COMPLETED
            step.result = result
            terminal_ui.print_success(f"{step.id} completed")

            # Save to execution scope
            execution_scope.add_message(
                LLMMessage(
                    role="assistant",
                    content=f"[{step.id} Completed]\n{result[:500]}...",
                )
            )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            self._failure_count += 1
            result = f"Step failed: {e}"
            logger.error(f"{step.id} failed: {e}")

        # Save step result summary to main memory
        await self.memory.add_message(
            LLMMessage(
                role="assistant",
                content=f"{step.id} ({step.description}): {result[:300]}...",
            )
        )

        return f"{step.id}: {step.description}\nResult: {result}"

    async def _execute_parallel_steps(
        self,
        steps: List[PlanStep],
        plan: ExecutionPlan,
        execution_scope: ScopedMemoryView,
    ) -> List[str]:
        """Execute multiple steps in parallel.

        Args:
            steps: Steps to execute
            plan: Current plan
            execution_scope: Execution memory scope

        Returns:
            List of step result strings
        """

        async def run_step(step: PlanStep) -> str:
            try:
                return await self._execute_step(step, plan, execution_scope)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                return f"Error: {e}"

        tasks_list = []
        async with asyncio.TaskGroup() as tg:
            for step in steps:
                tasks_list.append(tg.create_task(run_step(step)))

        return [task.result() for task in tasks_list]

    def _build_step_context(self, step: PlanStep, plan: ExecutionPlan) -> str:
        """Build context string for step execution.

        Args:
            step: Current step
            plan: Current plan

        Returns:
            Context string with previous step results
        """
        completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        if not completed:
            return "No previous steps completed."

        context_parts = []
        for s in completed[-5:]:  # Last 5 completed steps
            result_preview = (
                s.result[:300] + "..."
                if s.result and len(s.result) > 300
                else (s.result or "No result")
            )
            context_parts.append(f"{s.id}: {s.description}\nResult: {result_preview}")

        return "\n\n".join(context_parts)

    # ==================== REPLANNING ====================

    def _should_replan(self, plan: ExecutionPlan) -> bool:
        """Check if replanning is needed.

        Args:
            plan: Current plan

        Returns:
            True if replanning should be triggered
        """
        if self._failure_count >= self.REPLAN_THRESHOLD:
            return True

        # Check for blocked steps with failed dependencies
        for step in plan.steps:
            if step.status == StepStatus.PENDING:
                for dep_id in step.depends_on:
                    dep_step = next((s for s in plan.steps if s.id == dep_id), None)
                    if dep_step and dep_step.status == StepStatus.FAILED:
                        return True
        return False

    def _create_replan_request(self, plan: ExecutionPlan) -> ReplanRequest:
        """Create a replan request based on current state.

        Args:
            plan: Current plan

        Returns:
            ReplanRequest with failure information
        """
        failed_steps = [s for s in plan.steps if s.status == StepStatus.FAILED]
        if failed_steps:
            return ReplanRequest(
                trigger=ReplanTrigger.STEP_FAILURE,
                failed_step=failed_steps[-1],
                reason=failed_steps[-1].error or "Unknown error",
            )
        return ReplanRequest(
            trigger=ReplanTrigger.CONSTRAINT_VIOLATION,
            reason="Multiple steps cannot proceed",
        )

    async def _replan(self, current_plan: ExecutionPlan, request: ReplanRequest) -> ExecutionPlan:
        """Generate a new plan based on current state and failure information.

        Args:
            current_plan: The current plan
            request: Replan request with failure info

        Returns:
            Updated ExecutionPlan
        """
        terminal_ui.console.print()
        terminal_ui.console.print(f"[bold yellow]Replanning due to: {request.reason}[/bold yellow]")

        # Build replanner prompt
        prompt = REPLANNER_PROMPT.format(
            original_task=current_plan.task,
            current_plan=self._format_plan(current_plan),
            completed_steps=self._format_completed_steps(current_plan),
            failure_reason=request.reason,
            failed_step=request.failed_step.description if request.failed_step else "N/A",
        )

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self._call_llm(messages=messages)

        # Track tokens
        if response.usage:
            self.memory.token_tracker.add_input_tokens(response.usage.get("input_tokens", 0))
            self.memory.token_tracker.add_output_tokens(response.usage.get("output_tokens", 0))

        new_plan_text = self._extract_text(response)

        # Parse new plan
        new_plan = self._parse_plan(
            current_plan.task,
            new_plan_text,
            current_plan.exploration_context or ExplorationResult(),
        )
        new_plan.version = current_plan.version + 1

        # Mark steps that were already completed
        completed_descriptions = {
            s.description.lower(): s for s in current_plan.steps if s.status == StepStatus.COMPLETED
        }
        for step in new_plan.steps:
            if step.description.lower() in completed_descriptions:
                old_step = completed_descriptions[step.description.lower()]
                step.status = StepStatus.COMPLETED
                step.result = old_step.result

        # Save replan to memory
        await self.memory.add_message(
            LLMMessage(
                role="assistant",
                content=f"[Plan Updated - v{new_plan.version}]\nReason: {request.reason}\n{self._format_plan(new_plan)}",
            )
        )

        terminal_ui.console.print()
        terminal_ui.console.print(f"[green]Replan complete (v{new_plan.version})[/green]")
        terminal_ui.console.print(self._format_plan(new_plan), style="dim")

        return new_plan

    def _format_completed_steps(self, plan: ExecutionPlan) -> str:
        """Format completed steps with their results.

        Args:
            plan: Current plan

        Returns:
            Formatted string of completed steps
        """
        completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        if not completed:
            return "No steps completed yet."
        return "\n".join(f"{s.id}: {s.description}\nResult: {s.result}" for s in completed)

    # ==================== PHASE 4: SYNTHESIS ====================

    async def _synthesize(
        self, task: str, step_results: List[str], global_scope: ScopedMemoryView
    ) -> str:
        """Synthesize final answer from all results.

        Args:
            task: Original task
            step_results: List of step results
            global_scope: Global memory scope

        Returns:
            Final synthesized answer
        """
        exploration_summary = ""
        if self._exploration_results:
            exploration_summary = self._exploration_results.context_summary

        prompt = SYNTHESIZER_PROMPT.format(
            task=task,
            exploration_summary=exploration_summary,
            results="\n\n".join(step_results),
        )

        messages = [LLMMessage(role="user", content=prompt)]
        response = await self._call_llm(messages=messages)

        # Track tokens
        if response.usage:
            self.memory.token_tracker.add_input_tokens(response.usage.get("input_tokens", 0))
            self.memory.token_tracker.add_output_tokens(response.usage.get("output_tokens", 0))

        return self._extract_text(response)

    # ==================== UTILITIES ====================

    def _print_memory_stats(self):
        """Print memory usage statistics."""
        stats = self.memory.get_stats()
        terminal_ui.print_memory_stats(stats)
