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
from ouro.core.loop import Agent, Hook, NullProgressSink, ProgressSink

from .context.env import format_context_prompt
from .memory.hook import MemoryHook
from .memory.manager import MemoryManager
from .prompts import DEFAULT_SYSTEM_PROMPT
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
        # capability hooks (MemoryHook, VerificationHook) implement only the
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
            hooks.append(MemoryHook(memory))

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

        core = Agent(
            llm=self.llm,
            tools=tool_executor,
            hooks=hooks,
            max_iterations=self.max_iterations,
            progress=self.progress,
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
            return await self._core.run(task)

        # 1) System prompt — only on first turn (memory.system_messages empty).
        if not self.memory.system_messages:
            await self._add_system_prompt()

        # 2) User message (text or multimodal with images).
        user_msg = await self._build_user_message(task, images)
        await self.memory.add_message(user_msg)

        # 3) Verification toggle is decided at build time. If caller asks for
        # verify=True but we didn't wire a VerificationHook, log a warning.
        if verify and not self._has_verification_hook():
            logger.warning(
                "ComposedAgent.run(verify=True) but no VerificationHook is "
                "wired — pass .with_verification() to AgentBuilder. Falling "
                "back to plain ReAct loop."
            )

        # 4) Drive the core loop. In memory-backed mode the MemoryHook owns
        # persisted conversation history; the core loop's local MessageList is
        # just transient per-run state.
        result = await self._core.run(task)

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

        # 6) Stats + flush.
        import contextlib

        stats = self.memory.get_stats()
        with contextlib.suppress(Exception):  # pragma: no cover — UI path
            self._progress.info(_format_memory_stats_line(stats))
        await self.memory.save_memory()
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
        self.memory = await MemoryManager.from_session(
            session_id,
            self.llm,
            sessions_dir=self._sessions_dir,
            memory_dir=self._memory_dir,
            progress=self._progress,
        )
        self.memory.set_todo_context_provider(_make_todo_context_provider(self.todo_list))
        # Re-bind in MemoryHook (recreate or rewire).
        for hook in self._core.hooks:
            if isinstance(hook, MemoryHook):
                hook.memory = self.memory
                break

    def get_memory_stats(self) -> dict:
        if self.memory is None:
            return {}
        return self.memory.get_stats()

    def get_session_messages(self) -> list[LLMMessage]:
        """Return persisted conversation messages for UI/session display.

        The core loop owns per-run transient message state. UI surfaces that
        need resumed-session history should go through this convenience method
        instead of reaching into `memory.short_term` directly.
        """
        if self.memory is None:
            return []
        return self.memory.get_context_for_llm()

    def get_session_message_count(self) -> int:
        """Return the number of persisted messages available for session UI."""
        return len(self.get_session_messages())

    def reset_memory(self) -> None:
        """Reset the agent's memory state (clear short-term + system messages).

        This is a convenience proxy so UI layers don't reach into
        `memory.reset()` directly.
        """
        if self.memory is not None:
            self.memory.reset()

    def rollback_incomplete_exchange(self) -> None:
        """Roll back the last incomplete assistant response with tool_calls.

        This prevents API errors about missing tool responses on the next turn.
        """
        if self.memory is not None:
            self.memory.rollback_incomplete_exchange()

    async def compact_memory(self):
        """Trigger a manual memory compression.

        Returns the same ``CompressedMemory`` result as
        ``MemoryManager.compress()``, or ``None`` if nothing to compress.
        """
        if self.memory is None:
            return None
        return await self.memory.compress()

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
        await self.memory.add_message(LLMMessage(role="system", content=system_content))

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


def _format_memory_stats_line(stats: dict) -> str:
    if not stats:
        return ""
    return (
        f"memory: {stats.get('message_count', 0)} msgs, "
        f"{stats.get('estimated_tokens', 0)} tokens "
        f"(comp×{stats.get('compression_count', 0)})"
    )
