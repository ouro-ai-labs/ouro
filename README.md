# Agentic Loop

A Python agentic loop system supporting both **ReAct** and **Plan-and-Execute** modes, with support for multiple LLM providers (Anthropic Claude, OpenAI GPT, Google Gemini).

## Features

- 🤖 **Two Agent Modes**:
  - **ReAct**: Reasoning-Acting loop, ideal for interactive problem-solving
  - **Plan-and-Execute**: Planning-Execution-Synthesis, perfect for complex multi-step tasks

- 🤖 **Multiple LLM Support**:
  - **Anthropic Claude** (Claude 3.5 Sonnet, Opus, etc.)
  - **OpenAI GPT** (GPT-4o, GPT-4 Turbo, GPT-3.5, etc.)
  - **Google Gemini** (Gemini 1.5 Pro, Flash, etc.)
  - Easy to switch between providers with configuration

- 🛠️ **Rich Toolset**:
  - File operations (read/write/search)
  - Python code execution/calculator
  - Web search (DuckDuckGo)
  - Shell command execution (optional)

- 🎓 **Learning-Friendly**:
  - Clean, concise code (~1500 lines)
  - Modular design, easy to understand
  - Comprehensive comments and documentation

## Quick Start

### 1. Installation

```bash
# Clone the project
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
LLM_PROVIDER=anthropic

# Add the corresponding API key
ANTHROPIC_API_KEY=your_api_key_here
# OPENAI_API_KEY=your_api_key_here
# GEMINI_API_KEY=your_api_key_here

# Optional: specify a model (uses provider defaults if not set)
# MODEL=claude-3-5-sonnet-20241022
# MODEL=gpt-4o
# MODEL=gemini-1.5-pro
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

#### Enable Shell Tool

```bash
python main.py --enable-shell --task "List all Python files in current directory"
```

#### Interactive Input

```bash
python main.py --mode react
# Then enter your task, press Enter twice to submit
```

## Usage Examples

### Simple Calculation

```bash
python main.py --task "Calculate the first 10 digits of pi"
```

### File Operations

```bash
python main.py --task "Create a file hello.txt with content 'Hello, Agent!'"
```

### Complex Task

```bash
python main.py --mode plan --task "Search for AI agent information, summarize key concepts, and save to summary.txt"
```

## Project Structure

```
agentic-loop/
├── README.md                    # This document
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
├── config.py                    # Configuration management
├── main.py                      # CLI entry point
├── test_basic.py                # Basic tests
├── llm/                         # LLM abstraction layer
│   ├── __init__.py
│   ├── base.py                  # BaseLLM abstract class
│   ├── anthropic_llm.py         # Anthropic Claude adapter
│   ├── openai_llm.py            # OpenAI GPT adapter
│   └── gemini_llm.py            # Google Gemini adapter
├── agent/                       # Agent implementations
│   ├── __init__.py
│   ├── base.py                  # BaseAgent abstract class
│   ├── react_agent.py           # ReAct mode
│   ├── plan_execute_agent.py   # Plan-and-Execute mode
│   └── tool_executor.py         # Tool execution engine
├── tools/                       # Tool implementations
│   ├── __init__.py
│   ├── base.py                  # BaseTool abstract class
│   ├── file_ops.py              # File operation tools
│   ├── calculator.py            # Code execution/calculator
│   ├── shell.py                 # Shell commands
│   └── web_search.py            # Web search
└── examples/                    # Example code
    ├── react_example.py         # ReAct mode example
    └── plan_execute_example.py  # Plan-Execute example
```

## Comparing the Two Modes

### ReAct Mode

**Use Cases**: Interactive problem-solving, tasks requiring flexible strategy adjustment

**Workflow**:
1. Think: Analyze the current situation
2. Act: Call tools
3. Observe: Review results
4. Repeat until complete

**Example**:
```python
from agent.react_agent import ReActAgent
from tools.calculator import CalculatorTool

agent = ReActAgent(api_key="your_key", tools=[CalculatorTool()])
result = agent.run("Calculate (123 + 456) * 789")
print(result)
```

### Plan-and-Execute Mode

**Use Cases**: Complex multi-step tasks, problems requiring holistic planning

**Workflow**:
1. Plan: Create a complete step-by-step plan
2. Execute: Execute each step sequentially
3. Synthesize: Integrate all results into final answer

**Example**:
```python
from agent.plan_execute_agent import PlanExecuteAgent
from tools.file_ops import FileReadTool, FileWriteTool

agent = PlanExecuteAgent(
    api_key="your_key",
    tools=[FileReadTool(), FileWriteTool()]
)
result = agent.run("Analyze data.csv file and generate report")
print(result)
```

## Extending the System

### Adding New Tools

1. Create a new tool class inheriting from `BaseTool`:

```python
# tools/my_tool.py
from .base import BaseTool
from typing import Dict, Any

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Describe tool functionality"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "param1": {
                "type": "string",
                "description": "Parameter description"
            }
        }

    def execute(self, param1: str) -> str:
        # Implement tool logic
        return f"Result: {param1}"
```

2. Register the tool in `main.py`:

```python
from tools.my_tool import MyTool

tools = [
    # ... other tools
    MyTool(),
]
```

### Creating New Agent Modes

1. Inherit from `BaseAgent` and implement `run` method:

```python
# agent/my_agent.py
from .base import BaseAgent

class MyAgent(BaseAgent):
    def run(self, task: str) -> str:
        # Implement custom agent loop
        pass
```

2. Add mode option in `main.py`.

## Configuration Options

All configuration is done via the `.env` file:

```bash
# LLM Provider (required)
LLM_PROVIDER=anthropic  # Options: anthropic, openai, gemini

# API Keys (set the one for your chosen provider)
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here

# Model (optional - uses provider defaults if not set)
# Anthropic: claude-3-5-sonnet-20241022, claude-3-opus-20240229, etc.
# OpenAI: gpt-4o, gpt-4-turbo, gpt-3.5-turbo, etc.
# Gemini: gemini-1.5-pro, gemini-1.5-flash, etc.
MODEL=

# Agent Configuration
MAX_ITERATIONS=10        # Maximum iteration loops

# Tool Configuration
ENABLE_SHELL=false       # Enable shell command execution
```

### Default Models by Provider

If no `MODEL` is specified, these defaults are used:
- **Anthropic**: `claude-3-5-sonnet-20241022`
- **OpenAI**: `gpt-4o`
- **Gemini**: `gemini-1.5-pro`

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
- [ ] Conversation memory to maintain context
- [ ] Parallel tool execution
- [ ] Better error recovery and retry mechanisms
- [ ] Detailed logging and tracing
- [ ] Human-in-the-loop for dangerous operations
- [ ] Multi-agent collaboration system

## License

MIT License

## Contributing

Issues and Pull Requests are welcome!
