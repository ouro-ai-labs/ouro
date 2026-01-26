# RFC-004: Composable Agent Architecture

## Summary

重构 Agent 系统，将 ReactAgent 作为唯一的原子单位，通过组合模式实现 PlanExecuteAgent 等复杂行为，同时引入网状 Memory 结构支持灵活的上下文共享。

## Status

**Implemented** - 2025-01

## Core Problems Solved

1. **Agent 不统一**：`_react_loop` 是方法而非独立 Agent，阶段执行不是真正的 Agent
2. **EXPLORE 任务固定**：硬编码了 `file_structure`, `code_patterns`, `constraints`
3. **Memory 层级固定**：GLOBAL → EXPLORATION → EXECUTION → STEP 是刚性层级
4. **委托模式不统一**：`delegate_subtask` 和阶段执行使用不同的抽象

## Design Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      AgentRuntime                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    MemoryGraph                         │  │
│  │   MemNode(root) ←──→ MemNode(child1)                  │  │
│  │        ↑                  ↑                            │  │
│  │        └────────┬─────────┘                            │  │
│  │                 ↓                                      │  │
│  │          MemNode(child2) ← 多父节点支持                │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                  ReactAgent Pool                       │  │
│  │   ReactAgent(root) ──spawn──→ ReactAgent(explorer)    │  │
│  │         │                           │                  │  │
│  │         └──spawn──→ ReactAgent(executor)              │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. AgentConfig
```python
@dataclass
class AgentConfig:
    task: str
    tools: List[BaseTool]
    memory_node_id: str
    role_prompt: str = ""
    tool_filter: Optional[Set[str]] = None  # e.g., {"read_file", "grep_content"}
```

### 2. ReactAgent (Refactored)
- 唯一的原子 Agent 类型
- 新增 `_assess_composition_need(task)` → 动态判断是否需要分解
- 新增 `delegate(subtask, inherit_context, tool_filter)` → 统一委托机制
- 新增组合模式执行器：`_execute_plan_pattern()`, `run_with_composition()`

### 3. CompositionPlan
```python
class CompositionPattern(Enum):
    NONE = "none"                    # 直接执行
    PLAN_EXECUTE = "plan_execute"    # 探索→规划→执行→综合
    PARALLEL_EXPLORE = "parallel_explore"
    SEQUENTIAL_DELEGATE = "sequential_delegate"

@dataclass
class CompositionPlan:
    should_compose: bool
    pattern: CompositionPattern
    exploration_aspects: List[ExplorationAspect]  # 动态生成，非硬编码
    subtasks: List[SubtaskSpec]
```

### 4. MemoryGraph (Replaces ScopedMemoryView)
```python
@dataclass
class MemoryNode:
    id: str
    messages: List[LLMMessage]
    parent_ids: List[str]  # 支持多父节点
    child_ids: List[str]
    summary: Optional[str]

    def get_context_for_llm(self) -> List[LLMMessage]:
        """包含所有祖先的摘要 + 本地消息"""

    async def summarize(self) -> str:
        """LLM 生成摘要，压缩本地消息"""

class MemoryGraph:
    nodes: Dict[str, MemoryNode]

    def create_node(parent_id=None, parent_ids=None) -> MemoryNode
    def link_nodes(child_id, parent_id)
    async def merge_nodes(source_ids, target_id)  # 合并并行结果
```

### 5. AgentRuntime
```python
class AgentRuntime:
    llm: LiteLLMAdapter
    tools: List[BaseTool]
    memory_graph: MemoryGraph
    agents: Dict[str, ReactAgent]

    def spawn_agent(config: AgentConfig) -> ReactAgent
    def create_root_agent(task: str) -> ReactAgent
    async def run(task: str) -> str
```

## Execution Flow

```
User Task
    ↓
AgentRuntime.run(task)
    ↓
spawn ReactAgent(root) with MemoryNode(root)
    ↓
ReactAgent._assess_composition_need(task)
    ↓ (LLM decides)
┌─────────────────────────────────────────────────┐
│ CompositionPlan:                                │
│   pattern: PLAN_EXECUTE                         │
│   exploration_aspects: ["api设计", "现有模式"]  │  ← 动态生成
│   subtasks: [...]                               │
└─────────────────────────────────────────────────┘
    ↓
ReactAgent._execute_plan_pattern(plan)
    │
    ├── EXPLORE: 并行 delegate() 每个 aspect
    │      └── 创建子 MemoryNode (parent=root)
    │      └── spawn ReactAgent with tool_filter=read_only
    │      └── 执行后 summarize() → 合并到 parent
    │
    ├── PLAN: LLM 调用生成 ExecutionPlan
    │
    ├── EXECUTE: 按依赖顺序 delegate() 每个 step
    │      └── 创建子 MemoryNode (parent=root)
    │      └── spawn ReactAgent with full tools
    │
    └── SYNTHESIZE: LLM 调用生成最终答案
```

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `agent/composition.py` | **CREATE** | CompositionPlan, CompositionPattern, SubtaskSpec, AgentConfig |
| `agent/runtime.py` | **CREATE** | AgentRuntime 协调层 |
| `memory/graph.py` | **CREATE** | MemoryGraph, MemoryNode 网状内存 |
| `agent/prompts/composition_prompts.py` | **CREATE** | 组合评估提示词 |
| `agent/react_agent.py` | **MODIFY** | 添加组合逻辑、统一 delegate |
| `agent/base.py` | **MODIFY** | 标记 `delegate_subtask` 为 deprecated |
| `memory/scope.py` | **DEPRECATE** | 被 MemoryGraph 替代，添加 deprecation warning |
| `memory/store.py` | **MODIFY** | 添加 memory_nodes/memory_edges 表支持图持久化 |
| `main.py` | **MODIFY** | 使用 AgentRuntime 作为入口，添加 compose 模式 |
| `agent/__init__.py` | **MODIFY** | 导出新组件 |
| `memory/__init__.py` | **MODIFY** | 导出 MemoryGraph, MemoryNode |

## Design Decisions

### 1. Explore 策略：LLM 动态生成
完全由 LLM 根据任务内容动态决定需要探索哪些方面，不使用预定义模板。

```python
# composition_prompts.py
COMPOSITION_ASSESSMENT_PROMPT = """
分析任务，决定是否需要分解，以及需要探索哪些方面。
输出 JSON：
{
  "should_compose": true/false,
  "pattern": "plan_execute" | "parallel_explore" | "none",
  "exploration_aspects": ["aspect1", "aspect2", ...],  // 动态生成
  "reasoning": "..."
}
"""
```

### 2. Memory 完整持久化
保存整个 MemoryGraph 结构到数据库，支持跨会话恢复 agent 组合状态。

```sql
-- memory/store.py 新增表结构
CREATE TABLE memory_nodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    messages TEXT,  -- JSON
    summary TEXT,
    metadata TEXT,  -- JSON
    created_at TEXT
);

CREATE TABLE memory_edges (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES memory_nodes(id),
    FOREIGN KEY (child_id) REFERENCES memory_nodes(id)
);
```

### 3. 资源限制：深度 + 总数双重保护
```python
@dataclass
class RuntimeConfig:
    max_depth: int = 3        # agent 嵌套最大深度
    max_agents: int = 10      # 单次任务最大 agent 数量

class AgentRuntime:
    def spawn_agent(self, config: AgentConfig, depth: int = 0) -> ReactAgent:
        if depth >= self.config.max_depth:
            raise MaxDepthExceededError(...)
        if len(self.agents) >= self.config.max_agents:
            raise MaxAgentsExceededError(...)
```

## Backward Compatibility

```python
# 旧 API (保持可用，但会有 deprecation warning)
agent = ReActAgent(llm, tools)
result = await agent.run(task)

# 新 API
runtime = AgentRuntime(llm, tools)
result = await runtime.run(task)

# 使用 compose 模式（自动评估是否需要组合）
result = await agent.run_with_composition(task)
```

## CLI Usage

```bash
# 标准 react 模式（无变化）
python main.py --mode react --task "Calculate 1+1"

# plan-execute 模式（无变化）
python main.py --mode plan --task "Analyze codebase"

# 新增 compose 模式（自动组合）
python main.py --mode compose --task "Refactor auth system" --max-depth 5 --max-agents 15
```

## Tests

新增测试文件：
- `test/agent/test_composition.py` - 18 tests
- `test/memory/test_graph.py` - 27 tests
- `test/agent/test_runtime.py` - 13 tests

总计 58 个新测试，全部通过。

## Migration Guide

### From ScopedMemoryView to MemoryGraph

```python
# 旧代码
from memory.scope import ScopedMemoryView, MemoryScope
view = ScopedMemoryView(manager, MemoryScope.EXPLORATION, parent_view=parent)
view.add_message(msg)
context = view.get_context()

# 新代码
from memory.graph import MemoryGraph, MemoryNode
graph = MemoryGraph(llm=llm)
node = graph.create_node(parent_id=parent_node.id, metadata={"scope": "exploration"})
node.add_message(msg)
context = graph.get_context_for_llm(node.id)
```

### From delegate_subtask to delegate

```python
# 旧代码（仍可用，但有 deprecation warning）
result = await agent.delegate_subtask(description, include_context=True)

# 新代码
result = await agent.delegate(
    subtask=description,
    inherit_context=True,
    tool_filter={"read_file", "glob_files"},  # 可选：限制工具
)
```

## Future Work

1. **压缩协调**：多个子节点同时 summarize 时，使用增量摘要机制
2. **循环检测优化**：大规模图的 BFS 循环检测性能优化
3. **可视化**：MemoryGraph 的可视化工具
4. **更多组合模式**：支持 SEQUENTIAL_DELEGATE 等模式的完整实现
