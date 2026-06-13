# RFC: Swarm Task-Graph Execution

- Status: Draft
- Authors: ouro-ai-lab
- Date: 2026-06-13

## Summary

Redesign complex-task execution so swarm runs as a first-class execution strategy on top of Task V2 instead of a hook that mutates `agent.run()` state. The analyzer only decides whether to use swarm; a planner creates a Task V2 graph with dependencies; the swarm runtime executes that graph and a synthesizer returns the final result.

## Problem

The current auto-swarm flow mixes routing, planning, execution, and result delivery in the wrong places.

Concrete issues in the current implementation:
- `TaskAnalyzer` decides complexity and also returns execution-ready subtasks, biasing the system toward independent parallel work even when the task has dependencies.
- `AutoSwarmHook` runs swarm work inside `on_run_start`, even though the hook protocol has no short-circuit or alternate-return contract.
- Swarm output is injected back into the conversation as a `system` message, which pollutes the system-instruction layer with transient execution results.
- Task V2 already models dependencies and ownership, but the auto-swarm path bypasses that design by treating the analyzer's subtask list as the source of truth.

Example: a user asks for a non-trivial repo change that requires inspection, implementation, and regression testing. The current analyzer is encouraged to emit several unrelated subtasks and the hook executes them as if they were independent. In practice, those steps are often partially serial and should be represented as a dependency graph.

## Goals

- Make swarm a first-class execution path rather than a hook side effect.
- Make Task V2 the source of truth for all swarm task state.
- Restrict the analyzer to routing decisions only.
- Introduce a planner that produces a Task V2-compatible task graph with dependencies.
- Preserve existing single-agent `agent.run()` behavior for simple tasks.
- Keep the initial implementation incremental and reviewable.

## Non-goals

- Redesign the core ReAct loop for all agent features.
- Make every task, including trivial ones, go through Task V2.
- Implement mailbox-driven multi-agent collaboration in the first slice.
- Remove existing Task V2 tools or change their user-facing semantics.
- Solve dynamic replanning and mid-flight task graph mutation in the first slice.

## Proposed Behavior (User-Facing)

Complex tasks use a task-graph execution strategy:
- The system first analyzes whether the request is complex enough to benefit from swarm execution.
- If not, the request runs through the normal single-agent path.
- If yes, the system creates a Task V2 graph, including dependencies between tasks.
- The swarm runtime executes available tasks from the shared task store.
- After execution, the system returns a synthesized final answer based on task results and overall graph state.

Simple tasks keep the current behavior:
- Normal `agent.run()` flow remains the default path.
- No temporary swarm result is written into the system prompt or message history.

- CLI / UX changes:
  - No new required flags in the first slice.
  - Swarm progress remains visible through progress events, but the final response comes from the execution path return value rather than prompt injection.
- Config changes:
  - None required in the first slice.
- Output / logging changes:
  - Logs distinguish analyzer routing, planner output, runtime execution, and synthesis.

## Invariants (Must Not Regress)

- Simple tasks still run through the normal single-agent loop.
- Existing Task V2 tools continue to work against the same task store format.
- The core hook protocol remains valid for compaction and verification.
- The core loop does not need to understand Task V2 or swarm-specific types.
- Progress sinks continue to receive swarm status events during swarm execution.

## Design Sketch (Minimal)

Introduce a capabilities-layer orchestration path with four explicit stages:

1. `TaskAnalyzer`
   - Input: user task.
   - Output: `{should_use_swarm, complexity_score, reasoning}`.
   - No execution subtasks.

2. `TaskPlanner`
   - Input: complex user task.
   - Output: a Task V2-compatible task graph with stable local IDs and `blockedBy` dependencies.

3. `SwarmRuntime`
   - Input: persisted task graph in `TaskStore`.
   - Behavior: spawn worker agents, claim available tasks, run them, update state, and recover stale work.
   - Existing `SwarmCoordinator` can serve as the initial runtime scheduler, but it should no longer be treated as the planner.

4. `ResultSynthesizer`
   - Input: original task plus the final task graph state.
   - Output: final user-facing answer.

Execution routing happens outside `core.Agent.run()`:
- simple task -> `ComposedAgent.run()`
- complex task -> `analyzer -> planner -> task store -> swarm runtime -> synthesizer`

This keeps `ouro.core` unchanged apart from optional future convenience APIs.

## Alternatives Considered

- Option A: Keep auto-swarm as an `on_run_start` hook and add a short-circuit return type.
  - Rejected for the first redesign because swarm is an execution strategy, not a lifecycle side effect. Extending hook semantics would add complexity to the core loop for a capabilities-layer concern.
- Option B: Keep analyzer-generated subtasks but improve the prompt so it emits dependencies.
  - Rejected because it still mixes routing and planning and makes the analyzer the wrong source of truth.
- Option C: Force all tasks through Task V2.
  - Rejected because trivial tasks would pay unnecessary complexity and latency costs.

## Test Plan

- Unit tests:
  - Update analyzer tests to assert routing output only.
  - Add planner tests for valid task graph output and dependency references.
  - Add dispatcher tests for simple-path vs swarm-path routing.
  - Keep runtime tests focused on Task V2 dependency execution and recovery.
- Targeted tests to run locally:
  - `./scripts/dev.sh test -q test/swarm/test_analyzer.py test/swarm/test_swarm.py`
  - `./scripts/dev.sh test -q test/swarm/`
  - `TYPECHECK_STRICT=1 ./scripts/dev.sh typecheck`
- Smoke run (one real CLI run):
  - `python -m ouro.interfaces.cli.entry --task "inspect and update the repo with tests"`

## Rollout / Migration

- Backward compatibility:
  - Keep `with_agent_team()` during the transition, but move it toward wiring the new execution path rather than attaching an auto-swarm hook.
  - Existing Task V2 databases remain compatible.
- Migration steps (if any):
  - No user migration needed in the first slice.
  - Internally, deprecate `AutoSwarmHook` once the dispatcher path is in place.

## Risks & Mitigations

- Risk: planner output may create invalid or cyclic dependency graphs.
  - Mitigation: validate planner output before persisting tasks; reject cycles in the first implementation.
- Risk: the first slice could leave two competing swarm paths in the codebase.
  - Mitigation: clearly mark the hook-based path deprecated and keep new tests only on the dispatcher path.
- Risk: final synthesis may be too shallow if worker task outputs are not captured well enough.
  - Mitigation: store execution metadata/results in task metadata and keep the initial synthesizer simple and deterministic where possible.
- Risk: builder wiring becomes more complex.
  - Mitigation: introduce explicit capabilities-layer runner objects instead of pushing more behavior into the core loop.

## Open Questions

- Should the planner be a dedicated class with its own LLM prompt, or a specialized coordinator agent built from `AgentBuilder`?
- Should synthesized task results be stored directly on tasks, or should the synthesizer inspect other artifacts as needed?
- What is the cleanest public entry point for complex-task execution: a dispatcher object, a new `ComposedAgent` method, or a separate team-oriented agent wrapper?
