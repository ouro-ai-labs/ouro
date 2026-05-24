"""AgentBuilder + ComposedAgent — canonical assembly of a hooks-wired agent.

End users typically don't construct the bare `ouro.core.loop.Agent`
themselves. They use `AgentBuilder` to wire together the LLM, tools,
memory, skills, soul, verification, and progress UI, then call
`.build()` to get a `ComposedAgent`.

`ComposedAgent` is `core.Agent` plus convenience proxies for
`memory`, `tool_executor`, model switching, session loading, and
session-history snapshots, so the existing TUI/bot consumers can keep
using familiar surfaces without reaching into loop or memory internals.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from ouro.core.llm import (
    LiteLLMAdapter,
    LLMMessage,
    ModelManager,
    display_reasoning_effort,
)
from ouro.core.log import get_logger
from ouro.core.loop import (
    Agent,
    Hook,
    MessageListContext,
    NullProgressSink,
    ProgressSink,
    Rule,
)

from .compaction.hook import CompactionHook
from .context.agents_md import load_agents_md
from .context.env import format_context_prompt
from .memory.manager import MemoryManager
from .prompts import DEFAULT_SYSTEM_PROMPT
from .rules import ReadBeforeWriteRule
from .skills.registry import SkillsRegistry
from .skills.render import render_skills_section
from .todo.state import TodoList
from .tools.base import BaseTool
from .tools.builtins.todo_tool import TodoTool
from .tools.executor import ToolExecutor
from .verification.hook import VerificationHook
from .verification.verifier import Verifier


class ImageInput(Protocol):
    """Capability-local Protocol for image attachments.

    The bot channel layer's `ImageData` (with `data: bytes`, `mime_type: str`)
    satisfies this structurally. Defining the Protocol here keeps the
    capabilities → interfaces import boundary clean.
    """

    @property
    def data(self) -> bytes: ...
    @property
    def mime_type(self) -> str: ...


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# AgentBuilder
# ---------------------------------------------------------------------------


@dataclass
class AgentBuilder:
    """Fluent builder for `ComposedAgent`.

    All `with_*` methods return `self` for chaining. `.build()` produces a
    fully wired `ComposedAgent`.
    """

    llm: LiteLLMAdapter | None = None
    model_manager: ModelManager | None = None
    tools: list[BaseTool] = field(default_factory=list)
    max_iterations: int = 1000
    sessions_dir: str | None = None
    memory_dir: str | None = None
    memory_enabled: bool = True
    skills_registry: SkillsRegistry | None = None
    soul_section: str | None = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    verifier: Verifier | None = None
    verification_max_iterations: int = 0  # 0 disables verification
    progress: ProgressSink = field(default_factory=NullProgressSink)
    extra_hooks: list[Hook] = field(default_factory=list)
    # Deterministic per-tool-call rules. ReadBeforeWriteRule is on by default;
    # `extra_rules` run after it. See `ouro.capabilities.rules`.
    read_before_write: bool = True
    extra_rules: list[Rule] = field(default_factory=list)

    # ---- LLM ----------------------------------------------------------------

    def with_llm(
        self, llm: LiteLLMAdapter, *, model_manager: ModelManager | None = None
    ) -> AgentBuilder:
        self.llm = llm
        self.model_manager = model_manager
        return self

    def with_max_iterations(self, n: int) -> AgentBuilder:
        self.max_iterations = n
        return self

    # ---- Tools --------------------------------------------------------------

    def with_tool(self, tool: BaseTool) -> AgentBuilder:
        self.tools.append(tool)
        return self

    def with_tools(self, tools: Iterable[BaseTool]) -> AgentBuilder:
        self.tools.extend(tools)
        return self

    # ---- Memory -------------------------------------------------------------

    def with_memory(
        self,
        *,
        sessions_dir: str | None = None,
        memory_dir: str | None = None,
    ) -> AgentBuilder:
        self.memory_enabled = True
        self.sessions_dir = sessions_dir
        self.memory_dir = memory_dir
        return self

    def without_memory(self) -> AgentBuilder:
        self.memory_enabled = False
        return self

    # ---- Skills / soul / system prompt --------------------------------------

    def with_skills(self, registry: SkillsRegistry) -> AgentBuilder:
        self.skills_registry = registry
        return self

    def with_soul(self, soul_section: str | None) -> AgentBuilder:
        self.soul_section = soul_section
        return self

    def with_system_prompt(self, prompt: str) -> AgentBuilder:
        self.system_prompt = prompt
        return self

    # ---- Verification -------------------------------------------------------

    def with_verification(
        self,
        *,
        max_iterations: int = 3,
        verifier: Verifier | None = None,
    ) -> AgentBuilder:
        self.verification_max_iterations = max_iterations
        self.verifier = verifier
        return self

    # ---- Progress sink + extra hooks ---------------------------------------

    def with_progress_sink(self, progress: ProgressSink) -> AgentBuilder:
        self.progress = progress
        return self

    def with_hook(self, hook: Hook) -> AgentBuilder:
        self.extra_hooks.append(hook)
        return self

    # ---- Rules --------------------------------------------------------------

    def with_rule(self, rule: Rule) -> AgentBuilder:
        self.extra_rules.append(rule)
        return self

    def without_read_before_write(self) -> AgentBuilder:
        self.read_before_write = False
        return self

    # ---- Build --------------------------------------------------------------

    def build(self) -> ComposedAgent:
        if self.llm is None:
            raise ValueError("AgentBuilder requires .with_llm(...) before .build()")

        # Build the tool registry. TodoTool is auto-injected so all builds get it.
        todo_list = TodoList()
        tools: list[BaseTool] = list(self.tools)
        tools.append(TodoTool(todo_list))
        tool_executor = ToolExecutor(tools)

        # Memory + hook (optional but typically on).
        # `Hook` is a structural Protocol with method-level optionality —
        # capability hooks (CompactionHook, VerificationHook) implement only the
        # methods they care about, and the loop dispatches via getattr.
        # Mypy can't see that, so we keep the runtime list as `list[Any]`.
        memory: MemoryManager | None = None
        hooks: list[Any] = []
        if self.memory_enabled:
            memory = MemoryManager(
                self.llm,
                sessions_dir=self.sessions_dir,
                memory_dir=self.memory_dir,
                progress=self.progress,
            )
            memory.set_todo_context_provider(_make_todo_context_provider(todo_list))
            hooks.append(CompactionHook(memory.compaction))

        # Verification hook (off by default).
        if self.verification_max_iterations > 0:
            hooks.append(
                VerificationHook(
                    self.llm,
                    max_iterations=self.verification_max_iterations,
                    verifier=self.verifier,
                    progress=self.progress,
                )
            )

        # Caller-provided extras run after first-party hooks.
        hooks.extend(self.extra_hooks)

        # Deterministic per-tool-call rules (the repeat breaker is added by the
        # core Agent itself). ReadBeforeWriteRule is on by default.
        rules: list[Rule] = []
        if self.read_before_write:
            rules.append(ReadBeforeWriteRule())
        rules.extend(self.extra_rules)

        core = Agent(
            llm=self.llm,
            tools=tool_executor,
            hooks=hooks,
            max_iterations=self.max_iterations,
            progress=self.progress,
            usage_callback=(memory.token_tracker.record_usage if memory is not None else None),
            rules=rules,
        )

        return ComposedAgent(
            core=core,
            llm=self.llm,
            model_manager=self.model_manager,
            tool_executor=tool_executor,
            todo_list=todo_list,
            memory=memory,
            skills_registry=self.skills_registry,
            soul_section=self.soul_section,
            system_prompt=self.system_prompt,
            progress=self.progress,
            sessions_dir=self.sessions_dir,
            memory_dir=self.memory_dir,
        )


def _make_todo_context_provider(todo_list: TodoList):
    def provider() -> str | None:
        items = todo_list.get_current()
        if not items:
            return None
        return todo_list.format_list()

    return provider


# ---------------------------------------------------------------------------
# ComposedAgent
# ---------------------------------------------------------------------------


class ComposedAgent:
    """Convenience wrapper around `core.loop.Agent` with stateful proxies.

    Provides:
    - `.run(task, verify=False, images=None)` — assembles system prompt,
      persists the user message if memory is enabled, then dispatches
      to the core loop.
    - `.memory`, `.tool_executor`, `.todo_list` — back-compat surfaces.
    - `.set_reasoning_effort(...)`, `.switch_model(...)`, `.load_session(...)`,
      `.get_memory_stats()`, `.get_session_messages()`,
      `.get_session_message_count()`, `.reset_memory()`, `.compact_memory()`,
      `.rollback_incomplete_exchange()`, `.session_id`, `.list_sessions()` —
      convenience proxies the TUI/bot consumers depend on.

    Contract note:
    - The core loop owns transient per-run messages.
    - Persisted/resumed conversation history should be accessed through
      `ComposedAgent` convenience methods rather than UI code reaching into
      `memory.short_term` directly.
    """

    def __init__(
        self,
        *,
        core: Agent,
        llm: LiteLLMAdapter,
        model_manager: ModelManager | None,
        tool_executor: ToolExecutor,
        todo_list: TodoList,
        memory: MemoryManager | None,
        skills_registry: SkillsRegistry | None,
        soul_section: str | None,
        system_prompt: str,
        progress: ProgressSink,
        sessions_dir: str | None,
        memory_dir: str | None,
    ) -> None:
        self._core = core
        self.llm = llm
        self.model_manager = model_manager
        self.tool_executor = tool_executor
        self.todo_list = todo_list
        self.memory = memory
        self.skills_registry = skills_registry
        self.soul_section = soul_section
        self._skills_section_override: str | None = None
        self._system_prompt = system_prompt
        self._progress = progress
        self._sessions_dir = sessions_dir
        self._memory_dir = memory_dir
        # Persistent conversation state across multi-turn runs.  System
        # messages stay fixed after the first turn; detached messages
        # accumulate user / assistant / tool exchanges.  The core loop
        # appends to ``_context.detached`` directly during ``run()``.
        self._context = MessageListContext()

        # Wire any tool that needs the agent reference (e.g., MultiTaskTool).
        for t in tool_executor.tools.values() if hasattr(tool_executor, "tools") else []:
            if hasattr(t, "set_parent_agent"):
                t.set_parent_agent(self)  # type: ignore[attr-defined]

    # ---- main entry ---------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        verify: bool = False,
        images: Sequence[ImageInput] | None = None,
    ) -> str:
        if self.memory is None:
            return await self._core.run(task, context=self._context)

        # 1) System prompt — only on first turn.
        if not self._context.has_system_messages:
            await self._add_system_prompt()

        # 2) User message (text or multimodal with images).
        user_msg = await self._build_user_message(task, images)
        self._context.detached.append(user_msg)

        # 3) Verification toggle is decided at build time. If caller asks for
        # verify=True but we didn't wire a VerificationHook, log a warning.
        if verify and not self._has_verification_hook():
            logger.warning(
                "ComposedAgent.run(verify=True) but no VerificationHook is "
                "wired — pass .with_verification() to AgentBuilder. Falling "
                "back to plain ReAct loop."
            )

        # 4) Drive the core loop.  The loop owns the conversation list
        # via ``_context``; hooks observe but don't substitute.
        result = await self._core.run(task, context=self._context)

        # 5) Replace any image content blocks with text placeholders to keep
        # the persisted memory small.
        if images and isinstance(user_msg.content, list):
            user_msg.content = [
                (
                    block
                    if block.get("type") != "image_url"
                    else {"type": "text", "text": "[Image was provided and analyzed]"}
                )
                for block in user_msg.content
            ]

        # 6) Flush memory.
        await self.memory.save_memory(context=self._context)
        return result

    # ---- proxies ------------------------------------------------------------

    def set_reasoning_effort(self, value: str | None) -> None:
        self._core.set_reasoning_effort(value)

    def set_skills_section(self, section: str | None) -> None:
        """Override the skills section rendering with a pre-rendered string.

        When set, this takes precedence over `skills_registry` for system
        prompt assembly. Pass `None` to fall back to registry-based rendering.
        """
        self._skills_section_override = section

    def set_soul_section(self, soul_section: str | None) -> None:
        """Set the soul/personality section to append to the system prompt."""
        self.soul_section = soul_section

    def get_reasoning_effort(self) -> str:
        return display_reasoning_effort(getattr(self._core, "_reasoning_effort", None))

    @property
    def max_iterations(self) -> int:
        return self._core.max_iterations

    async def load_session(self, session_id: str) -> None:
        if self.memory is None:
            raise RuntimeError("Cannot load_session: memory is not enabled.")
        self.memory, loaded = await MemoryManager.from_session(
            session_id,
            self.llm,
            sessions_dir=self._sessions_dir,
            memory_dir=self._memory_dir,
            progress=self._progress,
        )
        self.memory.set_todo_context_provider(_make_todo_context_provider(self.todo_list))
        # Replace persistent conversation context with what was loaded.
        self._context = loaded
        # Re-bind in CompactionHook (recreate or rewire).
        for hook in self._core.hooks:
            if isinstance(hook, CompactionHook):
                hook.compaction = self.memory.compaction
                break

    def get_memory_stats(self) -> dict:
        if self.memory is None:
            return {}
        return self.memory.get_stats(context=self._context)

    def get_session_messages(self) -> list[LLMMessage]:
        """Return persisted conversation messages for UI/session display.

        Reads from the loop-owned ``MessageListContext`` (system + detached).
        """
        return self._context.build_context()

    def get_session_message_count(self) -> int:
        """Return the number of persisted messages available for session UI."""
        return len(self.get_session_messages())

    def reset_memory(self) -> None:
        """Reset the agent's conversation state (system + detached messages).

        Long-term memory (cross-session) and persistence-side state on
        ``MemoryManager`` are preserved.
        """
        self._context.clear_system_messages()
        self._context.detached.clear()
        if self.memory is not None:
            self.memory.reset()

    def rollback_incomplete_exchange(self) -> None:
        """Roll back the last incomplete assistant response with tool_calls.

        Prevents API errors about missing tool responses on the next turn.
        """
        snap = self._context.detached.snapshot()
        if not snap:
            return
        last = snap[-1]
        if last.role == "assistant" and getattr(last, "tool_calls", None):
            self._context.detached.replace(snap[:-1])
            logger.debug("Removed incomplete assistant message with tool_calls")

    async def compact_memory(self):
        """Trigger a manual memory compression.

        Returns the same ``CompressedMemory`` result as
        ``MemoryManager.compress()``, or ``None`` if nothing to compress.
        """
        if self.memory is None:
            return None
        return await self.memory.compress(context=self._context)

    async def save_session(self) -> None:
        """Persist the current conversation to disk.

        No-op when memory is disabled.  Bot session_router uses this
        on shutdown / idle eviction; ``ComposedAgent.run`` already
        saves at the end of each turn.
        """
        if self.memory is None:
            return
        await self.memory.save_memory(context=self._context)

    @property
    def session_id(self) -> str | None:
        """Current memory session ID, or None if memory is disabled / not yet created."""
        return self.memory.session_id if self.memory is not None else None

    def switch_model(self, model_id: str) -> bool:
        if not self.model_manager:
            logger.warning("No model manager available for switching models")
            return False
        profile = self.model_manager.get_model(model_id)
        if not profile:
            logger.error(f"Model '{model_id}' not found")
            return False
        is_valid, error_msg = self.model_manager.validate_model(profile)
        if not is_valid:
            logger.error(f"Invalid model: {error_msg}")
            return False
        new_profile = self.model_manager.switch_model(model_id)
        if not new_profile:
            logger.error(f"Failed to switch to model '{model_id}'")
            return False
        new_llm = LiteLLMAdapter(
            model=new_profile.model_id,
            api_key=new_profile.api_key,
            api_base=new_profile.api_base,
            timeout=new_profile.timeout,
            drop_params=new_profile.drop_params,
        )
        self.llm = new_llm
        self._core.llm = new_llm
        if self.memory is not None:
            self.memory.llm = new_llm
            if hasattr(self.memory, "compressor") and self.memory.compressor:
                self.memory.compressor.llm = new_llm
        logger.info(f"Switched to model: {new_profile.model_id}")
        return True

    def get_current_model_info(self) -> dict | None:
        if self.model_manager:
            profile = self.model_manager.get_current_model()
            if not profile:
                return None
            return {
                "name": profile.model_id,
                "model_id": profile.model_id,
                "provider": profile.provider,
            }
        return None

    # ---- helpers ------------------------------------------------------------

    def _has_verification_hook(self) -> bool:
        return any(isinstance(h, VerificationHook) for h in self._core.hooks)

    async def _add_system_prompt(self) -> None:
        assert self.memory is not None
        system_content = self._system_prompt
        try:
            ctx = await format_context_prompt()
            system_content = system_content + "\n" + ctx
        except Exception:
            pass
        try:
            project_instructions = await load_agents_md()
            if project_instructions:
                system_content = system_content + "\n" + project_instructions
        except Exception:
            logger.warning("Failed to load AGENTS.md project instructions", exc_info=True)
        if self.memory.long_term:
            try:
                async with self._progress.spinner("Loading memory...", title="Working"):
                    ltm_section = await self.memory.long_term.load_and_format()
                if ltm_section:
                    system_content = system_content + "\n" + ltm_section
            except Exception:
                logger.warning("Failed to load long-term memory", exc_info=True)
        skills_section = self._skills_section_override
        if skills_section is None and self.skills_registry and self.skills_registry.skills:
            skills_section = render_skills_section(list(self.skills_registry.skills.values()))
        if skills_section:
            system_content = system_content + "\n\n" + skills_section
        if self.soul_section:
            system_content = (
                system_content
                + "\n\n<soul>\n"
                + "Embody the persona and tone defined below. "
                + "Follow its guidance unless higher-priority instructions override it.\n\n"
                + self.soul_section
                + "\n</soul>"
            )
        self._context.add_system_message(LLMMessage(role="system", content=system_content))

    async def _build_user_message(
        self, task: str, images: Sequence[ImageInput] | None
    ) -> LLMMessage:
        if not images:
            return LLMMessage(role="user", content=task)
        content_blocks: list[dict] = []
        if task:
            content_blocks.append({"type": "text", "text": task})
        for img in images:
            b64 = base64.b64encode(img.data).decode()
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.mime_type};base64,{b64}"},
                }
            )
        return LLMMessage(role="user", content=content_blocks)
