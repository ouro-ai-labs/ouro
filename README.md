# Agentic Loop

A Python agentic loop system supporting both **ReAct** and **Plan-and-Execute** modes, with intelligent memory management and support for multiple LLM providers (Anthropic Claude, OpenAI GPT, Google Gemini).

## Features

- 🤖 **Two Agent Modes**:
  - **ReAct**: Reasoning-Acting loop, ideal for interactive problem-solving
  - **Plan-and-Execute**: Planning-Execution-Synthesis, perfect for complex multi-step tasks

- 🧠 **Intelligent Memory Management**:
  - Automatic compression of old messages (30-70% token reduction)
  - LLM-driven summarization for context optimization
  - Token tracking and cost estimation
  - Multiple compression strategies (sliding window, selective, deletion)
  - Supports long-running tasks without context overflow

- 🛠️ **Advanced File Tools** (Phase 1):
  - **Glob**: Fast file pattern matching (`**/*.py`, `src/**/*.js`)
  - **Grep**: Regex-based content search with context/count modes
  - **Edit**: Surgical file editing without reading entire contents
  - **Todo List**: Complex task management with progress tracking

- 💰 **Smart Model Routing** (Phase 2 - NEW!):
  - **70-80% cost reduction** through intelligent model tier selection
  - **Light models** for simple operations (Haiku, GPT-4o-mini, Flash)
  - **Medium models** for standard reasoning (Sonnet, GPT-4o, Pro)
  - **Heavy models** only for complex tasks (Sonnet, GPT-4, Pro)
  - Automatic routing with real-time cost tracking
  - Zero quality degradation with smart rules

- 🤖 **Multiple LLM Support**:
  - **Anthropic Claude** (Claude 3.5 Sonnet, Haiku, Opus, etc.)
  - **OpenAI GPT** (GPT-4o, GPT-4o-mini, O1, O3, etc.)
  - **Google Gemini** (Gemini 1.5/2.0 Pro, Flash, etc.)
  - Easy switching between providers via configuration
  - Custom base URL support (proxies, Azure, local deployments)

- 🛠️ **Rich Toolset**:
  - File operations (read/write/search)
  - Python code execution/calculator
  - Web search (DuckDuckGo)
  - Shell command execution (optional)

- 🔄 **Robust & Resilient**:
  - Automatic retry with exponential backoff for rate limits (429 errors)
  - Handles API quota exhaustion gracefully
  - Configurable retry behavior per provider

- 🎓 **Learning-Friendly**:
  - Clean, modular architecture
  - Comprehensive documentation
  - Easy to extend and customize

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <your-repo>
cd agentic-loop

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Create `.env` file:

```bash
cp .env.example .env
```

Edit `.env` file and configure your LLM provider:

```bash
# Choose your LLM provider (anthropic, openai, or gemini)
LLM_PROVIDER=gemini

# Add the corresponding API key
ANTHROPIC_API_KEY=your_anthropic_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Optional: specify a model (uses provider defaults if not set)
# MODEL=claude-3-5-sonnet-20241022
# MODEL=gpt-4o
# MODEL=gemini-2.5-flash

# Phase 1 Feature Flags
ENABLE_TODO_SYSTEM=true                    # Enable todo list management
ENABLE_ADVANCED_TOOLS=true                 # Enable Glob/Grep/Edit tools
ENABLE_CONTEXT_INJECTION=true              # Enable environment/git context

# Phase 2: Smart Model Routing (70-80% cost reduction)
ENABLE_MODEL_ROUTING=true                  # Enable intelligent model tier selection
LIGHT_MODEL=claude-3-5-haiku-20241022      # Cheapest model for simple operations
MEDIUM_MODEL=claude-3-5-sonnet-20241022    # Balanced model for standard operations
HEAVY_MODEL=claude-3-5-sonnet-20241022     # Most capable model for complex reasoning

# Memory Management (optional, enabled by default)
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=25000         # Compress when context grows large
```

**Quick setup for different providers:**

- **Anthropic Claude**: Set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`
- **OpenAI GPT**: Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY`
- **Google Gemini**: Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`

### 3. Run

#### ReAct Mode (Interactive)

```bash
python main.py --mode react --task "Calculate 123 * 456"
```

#### Plan-and-Execute Mode (Planning)

```bash
python main.py --mode plan --task "Search for Python agent tutorials and summarize top 3 results"
```

#### Interactive Input

```bash
python main.py --mode react
# Then enter your task, press Enter twice to submit
```

## Memory Management

The system includes intelligent memory management that automatically optimizes token usage for long-running tasks:

```bash
python main.py --task "Complex multi-step task with many iterations..."

# Memory statistics shown at the end:
# --- Memory Statistics ---
# Total tokens: 45,234
# Compressions: 3
# Net savings: 15,678 tokens (34.7%)
# Total cost: $0.0234
```

**Key features:**
- Automatic compression when context grows large
- 30-70% token reduction for long conversations
- Multiple compression strategies
- Cost tracking across providers
- Transparent operation (no code changes needed)

See [Memory Management Documentation](docs/memory-management.md) for detailed information.

## Project Structure

```
agentic-loop/
├── README.md                    # This document
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
├── config.py                    # Configuration management
├── main.py                      # CLI entry point
├── docs/                        # 📚 Documentation
│   ├── examples.md              # Detailed usage examples
│   ├── configuration.md         # Configuration guide
│   ├── memory-management.md     # Memory system docs
│   ├── advanced-features.md     # Advanced features & optimization
│   └── extending.md             # Extension guide
├── llm/                         # LLM abstraction layer
│   ├── base.py                  # BaseLLM abstract class
│   ├── anthropic_llm.py         # Anthropic Claude adapter
│   ├── openai_llm.py            # OpenAI GPT adapter
│   ├── gemini_llm.py            # Google Gemini adapter
│   └── retry.py                 # Retry logic for rate limits
├── agent/                       # Agent implementations
│   ├── base.py                  # BaseAgent abstract class
│   ├── context.py               # Context injection
│   ├── react_agent.py           # ReAct mode
│   ├── plan_execute_agent.py   # Plan-and-Execute mode
│   ├── tool_executor.py         # Tool execution engine
│   └── todo.py                  # Todo list management
├── memory/                      # 🧠 Memory management system
│   ├── types.py                 # Core data structures
│   ├── manager.py               # Memory orchestrator
│   ├── short_term.py            # Short-term memory
│   ├── compressor.py            # LLM-driven compression
│   └── token_tracker.py         # Token tracking & costs
├── tools/                       # Tool implementations
│   ├── base.py                  # BaseTool abstract class
│   ├── file_ops.py              # File operation tools
│   ├── advanced_file_ops.py     # 🌟 Glob, Grep, Edit tools (Phase 1)
│   ├── todo.py                  # Todo list tool (Phase 1)
│   ├── calculator.py            # Code execution/calculator
│   ├── shell.py                 # Shell commands
│   └── web_search.py            # Web search
├── utils/                       # Utilities
│   └── logger.py                # Logging setup
└── examples/                    # Example code
    ├── react_example.py         # ReAct mode example
    └── plan_execute_example.py  # Plan-Execute example
```

## Documentation

- **[Examples](docs/examples.md)**: Detailed usage examples and patterns
- **[Configuration](docs/configuration.md)**: Complete configuration guide
- **[Memory Management](docs/memory-management.md)**: Memory system documentation
- **[Advanced Features](docs/advanced-features.md)**: Optimization and advanced techniques
- **[Extending](docs/extending.md)**: How to add tools, agents, and LLM providers

## Comparing the Two Modes

### ReAct Mode

**Best for**: Interactive problem-solving, tasks requiring flexible strategy adjustment

**Workflow**:
1. Think: Analyze the current situation
2. Act: Call tools
3. Observe: Review results
4. Repeat until complete

**Example**:
```python
from agent.react_agent import ReActAgent
from tools.calculator import CalculatorTool

agent = ReActAgent(llm=llm, tools=[CalculatorTool()])
result = agent.run("Calculate (123 + 456) * 789")
```

### Plan-and-Execute Mode

**Best for**: Complex multi-step tasks, problems requiring holistic planning

**Workflow**:
1. Plan: Create a complete step-by-step plan
2. Execute: Execute each step sequentially
3. Synthesize: Integrate all results into final answer

**Example**:
```python
from agent.plan_execute_agent import PlanExecuteAgent
from tools.file_ops import FileReadTool, FileWriteTool

agent = PlanExecuteAgent(
    llm=llm,
    tools=[FileReadTool(), FileWriteTool()]
)
result = agent.run("Analyze data.csv and generate report")
```

## Configuration Options

All configuration is done via `.env` file:

```bash
# LLM Provider (required)
LLM_PROVIDER=anthropic  # Options: anthropic, openai, gemini

# API Keys (set the one for your chosen provider)
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here

# Model (optional - uses provider defaults if not set)
MODEL=

# Agent Configuration
MAX_ITERATIONS=10        # Maximum iteration loops

# Tool Configuration
ENABLE_SHELL=false       # Enable shell command execution

# Memory Management
MEMORY_ENABLED=true
MEMORY_MAX_CONTEXT_TOKENS=100000
MEMORY_COMPRESSION_THRESHOLD=40000

# Base URLs (optional - for proxies, Azure, local deployments)
ANTHROPIC_BASE_URL=
OPENAI_BASE_URL=
GEMINI_BASE_URL=
```

See [Configuration Guide](docs/configuration.md) for detailed options and presets.

## Default Models by Provider

If no `MODEL` is specified, these defaults are used:

| Provider | Default Model |
|----------|--------------|
| Anthropic | `claude-3-5-sonnet-20241022` |
| OpenAI | `gpt-4o` |
| Gemini | `gemini-1.5-pro` |

## Testing

Run basic tests:

```bash
source venv/bin/activate
python test_basic.py
```

## Learning Resources

- **ReAct Paper**: [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- **Anthropic API Documentation**: [docs.anthropic.com](https://docs.anthropic.com)
- **Tool Use Guide**: [Tool Use (Function Calling)](https://docs.anthropic.com/en/docs/tool-use)

## Future Improvements

- [ ] Streaming output to display agent thinking process
- [x] Intelligent memory management with compression
- [ ] Parallel tool execution
- [ ] Detailed logging and tracing
- [ ] Human-in-the-loop for dangerous operations
- [ ] Multi-agent collaboration system
- [ ] Persistent memory with session recovery
- [ ] Semantic retrieval with vector database

## License

MIT License

## Contributing

Issues and Pull Requests are welcome!
