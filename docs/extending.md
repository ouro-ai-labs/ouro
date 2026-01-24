# Extending the System

This guide shows you how to extend the Agentic Loop system with custom tools, agents, and LLM providers.

## Adding New Tools

Tools are the building blocks that agents use to interact with the world. Here's how to create custom tools.

## AsyncIO Migration Note (RFC 003)

AgenticLoop is migrating to an **asyncio-first** runtime. While this migration is in progress:

- Prefer **non-blocking** implementations for new tools (async HTTP/subprocess/DB where possible).
- Avoid introducing new blocking calls (`requests`, `sqlite3`, `subprocess.run`, `time.sleep`) in runtime paths.
- Do **not** call `asyncio.run()` inside tools or agents; only entrypoints should own the event loop.

See `rfc/003-asyncio-migration.md` for the phased plan and rules.

### Basic Tool Structure

1. Create a new file in the `tools/` directory:

```python
# tools/my_custom_tool.py
from .base import BaseTool
from typing import Dict, Any

class MyCustomTool(BaseTool):
    """Custom tool that does something useful."""

    @property
    def name(self) -> str:
        """Return the tool's name (used by LLM to identify the tool)."""
        return "my_custom_tool"

    @property
    def description(self) -> str:
        """Describe what this tool does (helps LLM decide when to use it)."""
        return "Performs a custom operation on the input data"

    @property
    def parameters(self) -> Dict[str, Any]:
        """Define the tool's parameters (JSON Schema format)."""
        return {
            "input_text": {
                "type": "string",
                "description": "The text to process"
            },
            "option": {
                "type": "string",
                "description": "Processing option (e.g., 'uppercase', 'lowercase')",
                "enum": ["uppercase", "lowercase", "reverse"]
            }
        }

    def execute(self, input_text: str, option: str = "uppercase") -> str:
        """Execute the tool's logic.

        Args:
            input_text: Text to process
            option: How to process it

        Returns:
            Processed text
        """
        if option == "uppercase":
            return input_text.upper()
        elif option == "lowercase":
            return input_text.lower()
        elif option == "reverse":
            return input_text[::-1]
        else:
            raise ValueError(f"Unknown option: {option}")
```

2. Register the tool in `main.py`:

```python
from tools.my_custom_tool import MyCustomTool

# In the create_default_tools() function or where you initialize tools:
tools = [
    CalculatorTool(),
    FileReadTool(),
    FileWriteTool(),
    MyCustomTool(),  # Add your tool here
    # ... other tools
]
```

### Tool Best Practices

1. **Clear Descriptions**: Make sure the `description` clearly explains what the tool does and when to use it
2. **Validate Inputs**: Always validate parameters in the `execute` method
3. **Error Handling**: Return descriptive error messages instead of raising exceptions
4. **Keep it Focused**: Each tool should do one thing well
5. **Document Parameters**: Use detailed parameter descriptions to help the LLM understand

### Example: API Client Tool

Here's a more complex example that makes HTTP requests:

```python
# tools/api_client.py
from .base import BaseTool
from typing import Dict, Any
import requests

class APIClientTool(BaseTool):
    """Tool for making HTTP API requests."""

    @property
    def name(self) -> str:
        return "api_request"

    @property
    def description(self) -> str:
        return "Make HTTP requests to APIs (GET, POST, etc.)"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "url": {
                "type": "string",
                "description": "The API endpoint URL"
            },
            "method": {
                "type": "string",
                "description": "HTTP method",
                "enum": ["GET", "POST", "PUT", "DELETE"]
            },
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers",
                "required": False
            },
            "body": {
                "type": "object",
                "description": "Optional request body (for POST/PUT)",
                "required": False
            }
        }

    def execute(self, url: str, method: str = "GET",
                headers: Dict = None, body: Dict = None) -> str:
        """Make an HTTP request."""
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers or {},
                json=body
            )
            response.raise_for_status()

            return f"Status: {response.status_code}\n\n{response.text}"
        except requests.exceptions.RequestException as e:
            return f"Error making request: {str(e)}"
```

**Note**: During the asyncio migration, prefer an async HTTP client for new tools, or ensure any blocking
HTTP is executed behind an async boundary (see `rfc/003-asyncio-migration.md`).

### Example: Database Tool

```python
# tools/database.py
from .base import BaseTool
from typing import Dict, Any
import sqlite3

class DatabaseTool(BaseTool):
    """Tool for executing SQL queries."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @property
    def name(self) -> str:
        return "sql_query"

    @property
    def description(self) -> str:
        return "Execute SQL queries on the SQLite database"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "description": "The SQL query to execute (SELECT only for safety)"
            }
        }

    def execute(self, query: str) -> str:
        """Execute a SQL query."""
        # Safety check: only allow SELECT queries
        if not query.strip().upper().startswith("SELECT"):
            return "Error: Only SELECT queries are allowed for safety"

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
            conn.close()

            if not results:
                return "Query returned no results"

            # Format results as a table
            return "\n".join([str(row) for row in results])
        except sqlite3.Error as e:
            return f"Database error: {str(e)}"
```

**Note**: During the asyncio migration, prefer an async SQLite strategy for new runtime code, or ensure
blocking DB calls are executed behind an async boundary (see `rfc/003-asyncio-migration.md`).

## Creating New Agent Modes

You can create custom agent modes by inheriting from `BaseAgent`.

### Basic Agent Structure

```python
# agent/my_custom_agent.py
from .base import BaseAgent
from llm.base import BaseLLM
from typing import List
from tools.base import BaseTool

class MyCustomAgent(BaseAgent):
    """Custom agent with a unique workflow."""

    def __init__(self, llm: BaseLLM, max_iterations: int = 10,
                 tools: List[BaseTool] = None):
        super().__init__(llm, max_iterations, tools)
        # Add custom initialization here

    def run(self, task: str) -> str:
        """Execute the agent's main loop.

        Args:
            task: The task to accomplish

        Returns:
            Final result
        """
        # Implement your custom agent logic here
        # This is where you define the unique behavior of your agent

        print(f"Starting custom agent for task: {task}")

        # Example: Simple loop
        for iteration in range(self.max_iterations):
            print(f"\n--- Iteration {iteration + 1} ---")

            # 1. Get LLM to decide what to do
            response = self._call_llm_with_tools(task)

            # 2. Execute any tool calls
            if response.tool_calls:
                for tool_call in response.tool_calls:
                    result = self.tool_executor.execute(
                        tool_call.name,
                        tool_call.arguments
                    )
                    print(f"Tool result: {result}")

            # 3. Check if task is complete
            if self._is_task_complete(response):
                return response.content

        return "Task not completed within max iterations"

    def _is_task_complete(self, response) -> bool:
        """Check if the task is done."""
        # Implement your completion logic
        return "FINAL_ANSWER:" in response.content
```

### Example: Collaborative Agent

Here's an agent that breaks tasks into subtasks and delegates:

```python
# agent/collaborative_agent.py
from .base import BaseAgent
from .react_agent import ReActAgent

class CollaborativeAgent(BaseAgent):
    """Agent that breaks tasks into subtasks and delegates to specialists."""

    SYSTEM_PROMPT = """You are a collaborative agent that breaks complex tasks
    into smaller subtasks and delegates them to specialist agents.

    For each task:
    1. Analyze and break it into 3-5 subtasks
    2. For each subtask, output: SUBTASK: <description>
    3. After all subtasks are complete, output: SYNTHESIS: <final answer>
    """

    def run(self, task: str) -> str:
        """Break task into subtasks and execute them."""
        # Step 1: Get subtasks from LLM
        subtasks = self._get_subtasks(task)
        print(f"Identified {len(subtasks)} subtasks")

        # Step 2: Execute each subtask with a specialist agent
        results = []
        for i, subtask in enumerate(subtasks):
            print(f"\n--- Subtask {i+1}: {subtask} ---")
            specialist = ReActAgent(
                llm=self.llm,
                max_iterations=5,
                tools=self.tool_executor.tools
            )
            result = specialist.run(subtask)
            results.append(result)

        # Step 3: Synthesize results
        final_answer = self._synthesize(task, subtasks, results)
        return final_answer

    def _get_subtasks(self, task: str) -> List[str]:
        """Use LLM to break task into subtasks."""
        # Implementation details...
        pass

    def _synthesize(self, task: str, subtasks: List[str],
                    results: List[str]) -> str:
        """Synthesize subtask results into final answer."""
        # Implementation details...
        pass
```

## Adding New LLM Providers

To add support for a new LLM provider:

### 1. Create Provider Adapter

```python
# llm/my_provider_llm.py
from .base import BaseLLM, LLMMessage, LLMResponse, ToolCall
from typing import List, Optional
import my_provider_sdk  # Your provider's SDK

class MyProviderLLM(BaseLLM):
    """Adapter for MyProvider's LLM API."""

    def __init__(self, api_key: str, model: str = "default-model", **kwargs):
        super().__init__(api_key, model, **kwargs)

        # Initialize provider client
        base_url = kwargs.get('base_url', None)
        if base_url:
            self.client = my_provider_sdk.Client(
                api_key=api_key,
                base_url=base_url
            )
        else:
            self.client = my_provider_sdk.Client(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "my_provider"

    def generate(self, messages: List[LLMMessage],
                 tools: Optional[List[dict]] = None,
                 **kwargs) -> LLMResponse:
        """Generate a response from the LLM."""
        try:
            # Convert to provider format
            provider_messages = self._convert_messages(messages)
            provider_tools = self._convert_tools(tools) if tools else None

            # Call provider API
            response = self.client.complete(
                model=self.model,
                messages=provider_messages,
                tools=provider_tools,
                **kwargs
            )

            # Convert response back to our format
            return self._convert_response(response)

        except my_provider_sdk.RateLimitError as e:
            # Handle rate limits with retry
            return self._handle_rate_limit(e, messages, tools, **kwargs)
        except Exception as e:
            raise Exception(f"Error calling MyProvider API: {str(e)}")

    def _convert_messages(self, messages: List[LLMMessage]) -> List[dict]:
        """Convert our message format to provider format."""
        return [{"role": msg.role, "content": msg.content}
                for msg in messages]

    def _convert_tools(self, tools: List[dict]) -> List[dict]:
        """Convert our tool format to provider format."""
        # Implement provider-specific tool format conversion
        pass

    def _convert_response(self, response) -> LLMResponse:
        """Convert provider response to our format."""
        tool_calls = []
        if hasattr(response, 'tool_calls'):
            for tc in response.tool_calls:
                tool_calls.append(ToolCall(
                    name=tc.name,
                    arguments=tc.arguments,
                    id=tc.id
                ))

        return LLMResponse(
            content=response.content,
            tool_calls=tool_calls if tool_calls else None
        )
```

### 2. Update Configuration

This repo is configured via LiteLLM (`LITELLM_MODEL` in `.env`). For most providers, **no code changes** are required:

```bash
LITELLM_MODEL=my_provider/my-model
MY_PROVIDER_API_KEY=...
```

If a provider is not supported by LiteLLM, implement a custom `BaseLLM` adapter under `llm/` and instantiate it directly in your app code (avoid adding more branching to `config.py`).

### 4. Update .env.example

```bash
# MyProvider Configuration
MY_PROVIDER_API_KEY=your_api_key_here
MY_PROVIDER_BASE_URL=  # Optional: custom API endpoint
```

## Testing Your Extensions

### Testing Tools

```python
# test_my_tool.py
from tools.my_custom_tool import MyCustomTool

def test_my_custom_tool():
    tool = MyCustomTool()

    # Test basic functionality
    result = tool.execute("hello", "uppercase")
    assert result == "HELLO"

    # Test different options
    result = tool.execute("WORLD", "lowercase")
    assert result == "world"

    print("All tests passed!")

if __name__ == "__main__":
    test_my_custom_tool()
```

### Testing Agents

```python
# test_my_agent.py
from agent.my_custom_agent import MyCustomAgent
from llm import LiteLLMLLM
from config import Config

def test_my_agent():
    llm = LiteLLMLLM(
        model=Config.LITELLM_MODEL,
        api_base=Config.LITELLM_API_BASE,
        drop_params=Config.LITELLM_DROP_PARAMS,
        timeout=Config.LITELLM_TIMEOUT,
        retry_config=Config.get_retry_config(),
    )

    agent = MyCustomAgent(llm=llm)
    result = agent.run("Test task")

    print(f"Result: {result}")
    assert result is not None

if __name__ == "__main__":
    test_my_agent()
```

## Best Practices

1. **Follow Existing Patterns**: Look at existing tools and agents for guidance
2. **Type Hints**: Use type hints for all parameters and return values
3. **Documentation**: Add docstrings to all classes and methods
4. **Error Handling**: Handle errors gracefully and return descriptive messages
5. **Testing**: Test your extensions before integrating them
6. **Modularity**: Keep extensions modular and focused on specific functionality

## Common Pitfalls

1. **Not Handling Tool Errors**: Always wrap tool execution in try-except
2. **Unclear Tool Descriptions**: LLM won't use your tool if it doesn't understand it
3. **Complex Parameters**: Keep tool parameters simple and well-documented
4. **Infinite Loops**: Always have a max iteration limit in agents
5. **API Format Mismatches**: Ensure you convert between formats correctly when adding LLM providers

## Next Steps

- See [Configuration](configuration.md) for environment setup
- See [Examples](examples.md) for usage patterns
- See [Advanced Features](advanced-features.md) for optimization techniques
