# RFC 001: Four-Phase Agent Architecture for Complex Task Execution

- **Status**: Implemented
- **Created**: 2025-01-24
- **Author**: ouro Team

## Abstract

This RFC presents an enhanced agent architecture that addresses fundamental limitations in traditional plan-and-execute patterns. By introducing a four-phase workflow—Explore, Plan, Execute, and Synthesize—combined with scoped memory management and parallel execution capabilities, we achieve more robust and efficient task completion for complex, multi-step operations.

## 1. Introduction

### 1.1 Background

Large Language Model (LLM) agents have evolved from simple prompt-response systems to sophisticated autonomous agents capable of executing complex tasks. The plan-and-execute pattern, where an agent first creates a plan and then executes each step, has emerged as a popular approach for handling multi-step tasks.

However, as we deployed agents in production environments, we observed several recurring failure patterns that motivated this architectural redesign.

### 1.2 Problem Statement

Traditional plan-execute agents suffer from three fundamental issues:

**The Blind Planning Problem**: Agents create plans without adequate context about the problem space. Like a chess player making moves without seeing the board, the agent commits to a strategy before understanding constraints, dependencies, or available resources.

**The Context Isolation Problem**: Each execution step operates in isolation, losing valuable context accumulated during previous steps. This leads to redundant exploration, inconsistent decisions, and failure to build upon earlier discoveries.

**The Rigid Execution Problem**: Once a plan is created, it becomes immutable. When steps fail or produce unexpected results, the agent has no mechanism to adapt, leading to cascading failures.

## 2. Design Philosophy

### 2.1 Core Principles

Our architecture is guided by four principles:

1. **Explore Before You Commit**: Gather context and validate assumptions before making irreversible decisions
2. **Preserve Context Across Phases**: Maintain memory continuity while allowing phase-specific isolation
3. **Embrace Parallelism**: Execute independent operations concurrently when safe to do so
4. **Fail Gracefully and Adapt**: Detect failures early and adjust plans dynamically

### 2.2 Inspiration from Human Problem-Solving

The four-phase architecture mirrors how experienced engineers approach complex problems:

1. **Explore**: "Let me first understand the codebase and existing patterns"
2. **Plan**: "Based on what I found, here's my approach"
3. **Execute**: "Now I'll implement each step, adjusting as I learn more"
4. **Synthesize**: "Let me summarize what was accomplished"

This human-like workflow produces more reliable results than mechanical plan execution.

## 3. Architecture Overview

### 3.1 Four-Phase Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│    │ EXPLORE  │───▶│   PLAN   │───▶│ EXECUTE  │───▶│SYNTHESIZE│
│    └──────────┘    └──────────┘    └────┬─────┘    └──────────┘
│                                         │                   │
│                         ┌───────────────┘                   │
│                         ▼                                   │
│                    ┌──────────┐                             │
│                    │ REPLAN   │ (on failure)                │
│                    └──────────┘                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Phase Responsibilities

| Phase | Purpose | Key Characteristics |
|-------|---------|---------------------|
| Explore | Gather context and discover constraints | Read-only, parallel agents, no side effects |
| Plan | Create structured, dependency-aware plan | Informed by exploration, identifies parallelism |
| Execute | Run plan steps with adaptive monitoring | Parallel batching, failure detection, replanning |
| Synthesize | Combine results into coherent output | Full context access, comprehensive summary |

## 4. Phase 1: Exploration

### 4.1 The Case for Exploration

Consider a task: "Refactor the authentication module to use JWT tokens."

A traditional agent might immediately plan steps like "1. Find auth files, 2. Modify token generation, 3. Update tests." But what if:
- The codebase already has a JWT library installed?
- There's an existing token validation middleware?
- The auth module has undocumented dependencies on session storage?

Without exploration, the agent discovers these constraints during execution, leading to plan failures and wasted effort.

### 4.2 Parallel Exploration Agents

We deploy multiple lightweight exploration agents concurrently, each focused on a specific aspect:

| Agent | Focus Area | Questions Answered |
|-------|------------|-------------------|
| Structure Explorer | File organization | What files exist? How is code organized? |
| Pattern Explorer | Code patterns | What conventions are used? What APIs exist? |
| Constraint Explorer | Limitations | What dependencies exist? What can't change? |

By running these in parallel, we gather comprehensive context with minimal latency overhead.

### 4.3 Read-Only Guarantee

Exploration agents are restricted to read-only operations. This is crucial for two reasons:

1. **Safety**: No accidental modifications before understanding the system
2. **Parallelism**: Read-only operations can safely run concurrently

## 5. Phase 2: Dependency-Aware Planning

### 5.1 From Linear Plans to Dependency Graphs

Traditional agents produce linear plans:
```
1. Do A
2. Do B
3. Do C
4. Do D
```

This assumes sequential dependencies that may not exist. Our planner produces dependency-aware plans:

```
1. Do A [independent]
2. Do B [independent, can parallel with A]
3. Do C [depends on A, B]
4. Do D [depends on C]
```

### 5.2 Parallelism Detection

The planner identifies steps that can execute concurrently:
- Steps with no dependencies form the initial parallel batch
- Steps whose dependencies are satisfied form subsequent batches
- The execution engine processes batches in waves

This transforms execution from O(n) to O(depth) where depth is the longest dependency chain.

### 5.3 Exploration-Informed Planning

The planner receives the full exploration context:
- Discovered files and their purposes
- Identified code patterns to follow
- Constraints that must be respected

This produces plans that are realistic and aligned with the existing codebase.

## 6. Scoped Memory Architecture

### 6.1 The Memory Continuity Challenge

A fundamental tension exists in agent memory management:

- **Global memory** provides context continuity but accumulates noise
- **Isolated memory** keeps phases clean but loses valuable context

We resolve this with scoped memory views.

### 6.2 Hierarchical Memory Scopes

```
┌─────────────────────────────────────────────┐
│           Global Memory (persistent)         │
│  ┌────────────────────────────────────────┐ │
│  │     Exploration Scope (summarized)      │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │      Execution Scope (summarized)       │ │
│  │  ┌──────────────────────────────────┐  │ │
│  │  │   Step Scope (local, temporary)   │  │ │
│  │  └──────────────────────────────────┘  │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### 6.3 Key Properties

**Context Inheritance**: Child scopes can access parent scope summaries, providing necessary context without full history.

**Isolation with Visibility**: Each phase operates in its own scope, preventing noise accumulation while maintaining awareness of prior work.

**Selective Persistence**: Only summaries propagate upward; detailed working memory stays local and is eventually discarded.

### 6.4 Benefits

| Approach | Context Access | Memory Efficiency | Phase Isolation |
|----------|---------------|-------------------|-----------------|
| Global only | Full | Poor | None |
| Isolated only | None | Good | Complete |
| Scoped (ours) | Summarized | Good | Balanced |

## 7. Parallel Execution Model

### 7.1 Execution Strategy

The execution phase processes steps in parallel batches:

```
Wave 1: [Step A, Step B]     ← No dependencies, run parallel
         ↓
Wave 2: [Step C]             ← Depends on A and B
         ↓
Wave 3: [Step D, Step E]     ← Both depend only on C, run parallel
         ↓
Wave 4: [Step F]             ← Depends on D and E
```

### 7.2 Thread Pool Design

We use a bounded thread pool for parallel execution:

- **Worker limit**: Prevents resource exhaustion (default: 4 workers)
- **Graceful degradation**: Falls back to sequential on parallel failures
- **Shared resources**: Workers share LLM client and memory manager

### 7.3 Safety Considerations

Not all steps can safely run in parallel. Our planner considers:

- **Resource conflicts**: Steps modifying the same file
- **Ordering requirements**: Steps where output order matters
- **Side effect interactions**: Steps with interdependent side effects

When in doubt, the planner marks steps as sequential.

## 8. Adaptive Replanning

### 8.1 Failure Detection

The execution engine monitors for:

- **Step failures**: Exceptions or error outputs
- **Blocked dependencies**: Steps waiting on failed predecessors
- **Threshold breaches**: Consecutive failures exceeding limit

### 8.2 Replan Triggers

Replanning activates when:
1. Failure count exceeds threshold (default: 2 consecutive failures)
2. A step's dependency has failed, blocking progress

### 8.3 Replan Strategy

The replanner receives:
- Original task description
- Current plan with step statuses
- Completed step results (preserved)
- Failure information

It produces a revised plan that:
- Preserves successfully completed work
- Addresses the failure with alternative approaches
- Maintains valid dependencies

### 8.4 Replan Limits

To prevent infinite loops, we limit:
- Maximum replan attempts per execution
- Cumulative failure tolerance
- Plan version tracking for debugging

## 9. Comparison with Existing Approaches

### 9.1 Traditional Plan-Execute

| Aspect | Traditional | Our Approach |
|--------|-------------|--------------|
| Context gathering | During execution | Dedicated exploration phase |
| Plan structure | Linear list | Dependency graph |
| Execution | Sequential | Parallel batches |
| Failure handling | Abort or continue | Adaptive replan |
| Memory | Global or isolated | Scoped hierarchy |

### 9.2 ReAct Pattern

ReAct (Reasoning + Acting) interleaves thinking and action in a single loop. Our approach differs:

- **ReAct**: Think → Act → Observe → Think → Act → ...
- **Ours**: Explore → Plan → (Execute → Observe → [Replan]) → Synthesize

ReAct excels at simple tasks; our approach handles complex multi-step operations with dependencies.

### 9.3 Tree of Thoughts

Tree of Thoughts explores multiple reasoning paths. We take a complementary approach:

- **ToT**: Explores solution space breadth
- **Ours**: Optimizes execution depth with parallelism

These approaches can be combined: ToT for planning, our architecture for execution.

## 10. Results and Observations

### 10.1 Qualitative Improvements

- **Better plans**: Exploration-informed plans align with codebase conventions
- **Faster execution**: Parallel batching reduces wall-clock time
- **Higher success rate**: Adaptive replanning recovers from failures
- **Cleaner memory**: Scoped approach prevents context pollution

### 10.2 Trade-offs

| Benefit | Cost |
|---------|------|
| Better context | Exploration overhead |
| Parallel speedup | Thread pool complexity |
| Failure recovery | Replan latency |
| Memory efficiency | Scope management overhead |

For simple tasks, the overhead may not be justified. The architecture shines on complex, multi-step operations.

## 11. Future Directions

### 11.1 Dynamic Exploration

Adapt exploration depth based on task complexity. Simple tasks skip or minimize exploration; complex tasks get deeper investigation.

### 11.2 Learning from Execution

Use execution outcomes to improve future plans. Failed approaches inform constraint discovery; successful patterns guide similar tasks.

### 11.3 Multi-Agent Coordination

Extend the architecture to coordinate multiple specialized agents, each handling different aspects of complex tasks.

### 11.4 Cost-Aware Scheduling

Incorporate token costs into parallelism decisions. Sometimes sequential execution with smaller context windows is more cost-effective.

## 12. Conclusion

The four-phase architecture addresses fundamental limitations in traditional plan-execute agents. By exploring before planning, preserving context through scoped memory, executing in parallel batches, and adapting to failures through replanning, we achieve more robust and efficient task completion.

The key insight is that agent architecture should mirror human problem-solving: understand the problem, make a plan, execute adaptively, and synthesize results. This human-inspired approach produces agents that handle complexity gracefully.

## References

1. Yao, S., et al. "ReAct: Synergizing Reasoning and Acting in Language Models." ICLR 2023.
2. Wang, L., et al. "Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning." ACL 2023.
3. Yao, S., et al. "Tree of Thoughts: Deliberate Problem Solving with Large Language Models." NeurIPS 2023.
4. AutoGPT, BabyAGI, and related autonomous agent projects.
5. Anthropic Claude Code architecture and design patterns.
