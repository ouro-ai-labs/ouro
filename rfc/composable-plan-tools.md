# RFC 004: Composable Planning Tools

## Status
Implemented

## Summary

Refactor the fixed four-phase Plan-Execute Agent into composable tools integrated into the ReAct agent's main loop, enabling the agent to autonomously decide when to explore and when to execute in parallel.

## Problem Statement

### Limitations of the Existing Approach

The original `PlanExecuteAgent` followed a fixed four-phase workflow:

```
EXPLORE → PLAN → EXECUTE → SYNTHESIZE
```

This design has several problems:

1. **Rigid workflow**: Regardless of task complexity, every task must go through all four phases. Simple tasks are forced to execute unnecessary exploration and planning steps.

2. **Two agent systems coexist**: Users must switch between ReAct and Plan modes via the `--mode` flag, increasing cognitive burden and code maintenance costs.

3. **Capabilities cannot be composed**: The exploration and parallel execution capabilities of Plan mode are locked into the fixed workflow; ReAct mode cannot leverage them.

4. **Granularity too coarse**: Sometimes you only need parallel exploration without the full planning workflow, but the existing design doesn't support such flexible composition.

### Design Goals

- **Unified entry point**: Keep only the ReAct agent, eliminate mode switching
- **Composable capabilities**: Expose exploration and parallel execution as independent tools
- **Agent autonomy**: Let the agent decide whether to use these capabilities based on task characteristics
- **Simplified architecture**: Reduce code duplication, lower maintenance costs

## Design

### Core Insight: From "Workflow" to "Tools"

Key observation: The four phases of Plan-Execute are essentially combinations of two capabilities:

| Phase | Essential Capability |
|-------|---------------------|
| EXPLORE | Parallel information gathering |
| PLAN | Task decomposition (existing todo_list tool) |
| EXECUTE | Parallel task execution |
| SYNTHESIZE | Result aggregation (native LLM capability) |

PLAN and SYNTHESIZE don't need dedicated tools—task decomposition can use the existing `manage_todo_list`, and result aggregation is a basic LLM capability. What truly needs to be toolified is **parallel exploration** and **parallel execution**.

### Tool Design

#### 1. explore_context - Parallel Exploration Tool

**Purpose**: Parallelization of the information gathering phase

**Design decisions**:
- Only allow read-only tools (glob, grep, read, code_navigator) and network tools (web_search, web_fetch)
- Limit concurrency (MAX_PARALLEL = 3) to prevent resource exhaustion
- Return compressed summaries (each result limited to 1500 characters) to protect context space

**Why not use delegate_subtask?**
- `delegate_subtask` is serial—can only execute one subtask at a time
- Exploration tasks are naturally parallel: multiple aspects can be investigated simultaneously
- Parallel exploration significantly improves efficiency, especially when needing to understand code structure and consult documentation simultaneously

#### 2. parallel_execute - Parallel Execution Tool

**Purpose**: Parallelization of the execution phase with dependency support

**Design decisions**:
- Support full tool set (both read and write operations)
- Support dependency declarations, execute in batches according to topological order
- Detect circular dependencies before execution to prevent deadlocks
- Allow calling `explore_context` (one level of nesting), forbid calling `parallel_execute` (prevent recursion)

**Why dependency support is necessary**:
In real tasks, steps often have dependencies. For example:
```
Task 0: Read config file
Task 1: Read data model
Task 2: Generate code based on config and model  ← depends on 0 and 1
```
Without dependency support, users can only execute serially or manually batch, losing the tool's value.

### Recursion Limiting Strategy

**Problem**: If `parallel_execute` subtasks could infinitely call `parallel_execute`, it would cause:
- Exponential explosion of the execution tree
- Resource exhaustion
- Difficulty in tracking and debugging

**Solution**: Allow one level of nesting
- Subtasks can call `explore_context` (exploration doesn't modify state, risk is controllable)
- Subtasks cannot call `parallel_execute` (enforced via tool filtering)

This is a pragmatic tradeoff: it covers the common "explore then execute" pattern while avoiding complexity explosion.

### Removing Redundancy

After refactoring, the following components become redundant:

1. **PlanExecuteAgent**: Functionality replaced by tool composition, marked as deprecated
2. **DelegationTool**: `explore_context` and `parallel_execute` fully cover its functionality
   - Single exploration task → `explore_context` with 1 task
   - Single execution task → `parallel_execute` with 1 task
3. **--mode flag**: Only ReAct mode remains

### System Prompt Strategy

Tool descriptions already contain specific usage details; the System Prompt only needs to provide **composition strategy**:

```
For complex tasks, combine tools to achieve an explore-plan-execute workflow:

1. EXPLORE: Use explore_context for parallel information gathering
2. PLAN: Use manage_todo_list to break down tasks
3. EXECUTE: Use parallel_execute for parallel workloads

When to use:
- Simple task → Use tools directly
- Medium task → Todo list + sequential execution
- Complex task → Explore → Plan → Execute
```

This avoids information duplication, letting the agent understand "when to compose" rather than "how to call".

## Alternatives Considered

### 1. Keep Plan Mode as a separate mode

**Rejected because**:
- Maintaining two sets of agent code
- Users need to predict task complexity to choose modes
- Capabilities cannot be shared across modes

### 2. Hardcode explore-plan-execute workflow in ReAct

**Rejected because**:
- Loses ReAct's flexibility
- Simple tasks forced through full workflow
- Essentially just Plan Mode with a different entry point

### 3. No recursion depth limit

**Rejected because**:
- Execution tree difficult to control
- Unpredictable resource consumption
- Hard to debug

### 4. Keep delegate_subtask as a lightweight option

**Rejected because**:
- Functionality completely covered by new tools
- Increases user decision burden (when to use delegate vs explore vs parallel_execute?)
- Fewer tools means clearer agent decision-making

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Exploration results too long causing context overflow | Truncate each result to 1500 characters |
| Circular dependencies causing deadlock | DFS cycle detection before execution |
| Subtasks recursively calling parallel_execute | Tool filter enforces prohibition |
| LLM doesn't know when to use new tools | System Prompt provides composition strategy guidance |
| Inconsistent state when parallel execution fails | Subtasks catch exceptions, return error messages for main agent to decide |

## Future Work

1. **Dynamic concurrency control**: Automatically adjust concurrency based on system load
2. **Execution progress visualization**: Display real-time status of parallel tasks
3. **Result caching**: Reuse results from identical exploration tasks
4. **Smarter dependency inference**: Let LLM automatically analyze task dependencies rather than requiring explicit user declaration
