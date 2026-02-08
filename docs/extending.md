# Extending ouro

## Adding Tools

Tools inherit from `BaseTool` and implement three properties plus an `execute` method.

### Interface

```python
# tools/my_tool.py
from tools.base import BaseTool
from typing import Dict, Any

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "One-line description (helps the LLM decide when to use it)"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "input_text": {
                "type": "string",
                "description": "The text to process",
            },
            "option": {
                "type": "string",
                "description": "Processing option",
                "enum": ["uppercase", "lowercase", "reverse"],
            },
        }

    async def execute(self, input_text: str, option: str = "uppercase") -> str:
        if option == "uppercase":
            return input_text.upper()
        elif option == "lowercase":
            return input_text.lower()
        elif option == "reverse":
            return input_text[::-1]
        raise ValueError(f"Unknown option: {option}")
```

### Registration

Add the tool in `main.py` where tools are instantiated:

```python
from tools.my_tool import MyTool

tools = [
    # ... existing tools ...
    MyTool(),
]
```

### Guidelines

- Use async I/O (`httpx`, `aiofiles`) in `execute`. Avoid blocking calls.
- Write clear `description` and parameter descriptions -- the LLM reads them.
- Return descriptive error messages instead of raising exceptions.
- Keep each tool focused on one operation.

## Creating Agents

Agents inherit from `BaseAgent`. The only built-in agent is `LoopAgent`.

```python
# agent/my_agent.py
from agent.base import BaseAgent
from typing import List
from tools.base import BaseTool

class MyAgent(BaseAgent):
    async def run(self, task: str) -> str:
        # Add the task as the initial user message
        await self.memory.add_message(
            LLMMessage(role="user", content=task)
        )

        for iteration in range(self.max_iterations):
            context = self.memory.get_context_for_llm()
            response = await self.llm.call_async(messages=context, tools=self.tool_schemas)

            if response.tool_calls:
                for tc in response.tool_calls:
                    result = await self.tool_executor.execute_tool_call(tc.name, tc.arguments)

            await self.memory.add_message(
                LLMMessage(role="assistant", content=response.content)
            )

            if self._is_done(response):
                return response.content

        return "Max iterations reached"
```

`BaseAgent` provides `_react_loop()` and `_ralph_loop()` methods. `LoopAgent.run()` calls `_ralph_loop()` for task mode (with verification) and `_react_loop()` for interactive mode.

## Adding LLM Providers

Most providers work out of the box via LiteLLM. Just add them to `~/.ouro/models.yaml`:

```yaml
models:
  my_provider/my-model:
    api_key: your_key
    api_base: https://custom.endpoint.com  # optional
default: my_provider/my-model
```

If a provider is not supported by LiteLLM, implement a custom adapter:

```python
# llm/my_provider.py
from llm.base import BaseLLM, LLMMessage, LLMResponse, ToolCall
from typing import List, Optional

class MyProviderLLM(BaseLLM):
    @property
    def provider_name(self) -> str:
        return "my_provider"

    async def call_async(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[dict]] = None,
        **kwargs,
    ) -> LLMResponse:
        # Convert messages to provider format, call API, convert response back
        ...
```

Then instantiate it directly in your code instead of going through `ModelManager`.

## Testing Extensions

```python
# test/test_my_tool.py
import pytest
from tools.my_tool import MyTool

@pytest.mark.asyncio
async def test_my_tool():
    tool = MyTool()
    assert await tool.execute("hello", "uppercase") == "HELLO"
    assert await tool.execute("WORLD", "lowercase") == "world"
```

Run:
```bash
python -m pytest test/test_my_tool.py -v
```

For integration tests that call real LLM APIs, gate them behind `RUN_INTEGRATION_TESTS=1`.
