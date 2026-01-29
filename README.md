# Agentic Loop

General AI Agent System

## Installation

Prerequisites for development:
- Python 3.12+
- `uv` (https://github.com/astral-sh/uv)

### Option 1: Install from PyPI (Recommended - Coming Soon)

```bash
pip install AgenticLoop
```

### Option 2: Install from Source (Development)

```bash
# Clone the repository
git clone https://github.com/yourusername/AgenticLoop.git
cd AgenticLoop

# Bootstrap (recommended)
./scripts/bootstrap.sh
```

### Option 3: Install from GitHub

```bash
pip install git+https://github.com/yourusername/AgenticLoop.git
```

### Option 4: Docker

```bash
docker pull yourusername/AgenticLoop:latest
docker run -it --rm -e ANTHROPIC_API_KEY=your_key AgenticLoop --mode react
```

## Quick Start

For repo workflow (install/test/format/build/publish), see `AGENTS.md`.

### 0. Install Dependencies (Recommended)

```bash
./scripts/bootstrap.sh
```

Optional (recommended): enable git hooks for consistent formatting/linting on commit:

```bash
source .venv/bin/activate
pre-commit install
```

### 1. Configuration

On first run, `.aloop/config` is created automatically with sensible defaults. Edit it to configure your LLM provider:

```bash
$EDITOR .aloop/config
```

Example `.aloop/config`:

```bash
# LiteLLM Model Configuration (supports 100+ providers)
# Format: provider/model_name
LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022

# API Keys (set the key for your chosen provider)
ANTHROPIC_API_KEY=your_anthropic_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Optional: Custom base URL for proxies or custom endpoints
LITELLM_API_BASE=

# Optional: LiteLLM-specific settings
LITELLM_DROP_PARAMS=true       # Drop unsupported params instead of erroring
LITELLM_TIMEOUT=600            # Request timeout in seconds

# Agent Configuration
MAX_ITERATIONS=100  # Maximum iteration loops

# Memory Management
MEMORY_ENABLED=true
MEMORY_COMPRESSION_THRESHOLD=25000
MEMORY_SHORT_TERM_SIZE=100
MEMORY_COMPRESSION_RATIO=0.3

# Retry Configuration (for handling rate limits)
RETRY_MAX_ATTEMPTS=3
RETRY_INITIAL_DELAY=1.0
RETRY_MAX_DELAY=60.0

# Logging
LOG_LEVEL=DEBUG
```

**Quick setup for different providers:**

- **Anthropic Claude**: `LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022`
- **OpenAI GPT**: `LITELLM_MODEL=openai/gpt-4o`
- **Google Gemini**: `LITELLM_MODEL=gemini/gemini-1.5-pro`
- **Azure OpenAI**: `LITELLM_MODEL=azure/gpt-4`
- **AWS Bedrock**: `LITELLM_MODEL=bedrock/anthropic.claude-v2`
- **Local (Ollama)**: `LITELLM_MODEL=ollama/llama2`

See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for 100+ supported providers.

### 2. Usage

#### Command Line (After Installation)

```bash
# Interactive mode
aloop

# Single task (ReAct mode)
aloop --mode react --task "Calculate 123 * 456"

# Single task (Plan-Execute mode)
aloop --mode plan --task "Build a web scraper"

# Show help
aloop --help
```

#### Direct Python Execution (Development)

If running from source without installation:

**ReAct Mode (Interactive)**

```bash
python main.py --mode react --task "Calculate 123 * 456"
```

**Plan-and-Execute Mode (Planning)**

```bash
python main.py --mode plan --task "Search for Python agent tutorials and summarize top 3 results"
```

**Interactive Input**

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
AgenticLoop/
├── README.md                    # This document
├── config.py                    # Configuration management
├── main.py                      # CLI entry point
├── docs/                        # 📚 Documentation
│   ├── examples.md              # Detailed usage examples
│   ├── configuration.md         # Configuration guide
│   ├── memory-management.md     # Memory system docs
│   ├── advanced-features.md     # Advanced features & optimization
│   └── extending.md             # Extension guide
├── llm/                         # LLM abstraction layer
│   ├── base.py                  # Base data structures (LLMMessage, LLMResponse)
│   ├── litellm_adapter.py       # LiteLLM adapter (100+ providers)
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
│   ├── manager.py               # Memory orchestrator with persistence
│   ├── short_term.py            # Short-term memory
│   ├── compressor.py            # LLM-driven compression
│   ├── token_tracker.py         # Token tracking & costs
│   └── store.py                 # SQLite-based persistent storage
├── tools/                       # Tool implementations
│   ├── base.py                  # BaseTool abstract class
│   ├── file_ops.py              # File operation tools (read/write/search)
│   ├── advanced_file_ops.py     # Advanced tools (Glob/Grep/Edit)
│   ├── calculator.py            # Code execution/calculator
│   ├── shell.py                 # Shell commands
│   ├── web_search.py            # Web search
│   ├── todo.py                  # Todo list management
│   └── delegation.py            # Sub-agent delegation
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
- **[Packaging Guide](docs/packaging.md)**: Package and distribute the system

## Configuration Options

See the [Configuration Guide](docs/configuration.md) for all options. Key settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `LITELLM_MODEL` | LiteLLM model (provider/model format) | `anthropic/claude-3-5-sonnet-20241022` |
| `LITELLM_API_BASE` | Custom base URL for proxies | Empty |
| `LITELLM_DROP_PARAMS` | Drop unsupported params | `true` |
| `LITELLM_TIMEOUT` | Request timeout in seconds | `600` |
| `MAX_ITERATIONS` | Maximum agent iterations | `100` |
| `MEMORY_COMPRESSION_THRESHOLD` | Compress when exceeded | `25000` |
| `MEMORY_SHORT_TERM_SIZE` | Recent messages to keep | `100` |
| `RETRY_MAX_ATTEMPTS` | Retry attempts for rate limits | `3` |
| `LOG_LEVEL` | Logging level | `DEBUG` |

See [Configuration Guide](docs/configuration.md) for detailed options.

## Testing

Run basic tests:

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
./scripts/dev.sh test -q
```

## Learning Resources

- **ReAct Paper**: [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- **Anthropic API Documentation**: [docs.anthropic.com](https://docs.anthropic.com)
- **Tool Use Guide**: [Tool Use (Function Calling)](https://docs.anthropic.com/en/docs/tool-use)

## Features

- ✅ **Multi-Provider Support**: 100+ LLM providers via LiteLLM (Anthropic, OpenAI, Google, Azure, AWS Bedrock, local models, etc.)
- ✅ **Intelligent Memory Management**: Automatic compression with 30-70% token reduction
- ✅ **Persistent Memory**: SQLite-based session storage and recovery
- ✅ **ReAct & Plan-Execute Modes**: Flexible agent architectures
- ✅ **Rich Tool Ecosystem**: File operations, web search, shell commands, code execution
- ✅ **Automatic Retry Logic**: Built-in handling for rate limits and API errors
- ✅ **Cost Tracking**: Token usage and cost monitoring across providers

## Future Improvements

- [ ] Streaming output to display agent thinking process
- [ ] Parallel tool execution
- [ ] Human-in-the-loop for dangerous operations
- [ ] Multi-agent collaboration system
- [ ] Semantic retrieval with vector database

## License

MIT License

## Development

### Building and Packaging

See the [Packaging Guide](docs/packaging.md) for instructions on:
- Building distributable packages
- Publishing to PyPI
- Creating Docker images
- Generating standalone executables

Quick commands:
```bash
# Bootstrap local dev environment (creates .venv, installs deps)
./scripts/bootstrap.sh

# Build distribution packages
./scripts/dev.sh build

# Publish to PyPI
./scripts/dev.sh publish
```

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

### How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
