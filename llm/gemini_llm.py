"""Google Gemini LLM implementation.

Note: This uses the legacy google.generativeai package which is deprecated.
For production use, consider migrating to the new google.genai package.
See: https://github.com/google-gemini/deprecated-generative-ai-python
"""
from typing import List, Dict, Any, Optional
import json
import warnings

from .base import BaseLLM, LLMMessage, LLMResponse, ToolCall, ToolResult
from .retry import with_retry, RetryConfig
from utils import get_logger

# Suppress the deprecation warning for now
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

logger = get_logger(__name__)


class GeminiLLM(BaseLLM):
    """Google Gemini LLM provider."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-pro", **kwargs):
        """Initialize Gemini LLM.

        Args:
            api_key: Google AI API key
            model: Gemini model identifier (e.g., gemini-1.5-pro, gemini-1.5-flash)
            **kwargs: Additional configuration (including retry_config, base_url)
        """
        super().__init__(api_key, model, **kwargs)

        # Configure retry behavior
        self.retry_config = kwargs.get('retry_config', RetryConfig(
            max_retries=5,
            initial_delay=2.0,
            max_delay=60.0
        ))

        try:
            import google.generativeai as genai

            # Get base_url from kwargs, or use None (default)
            base_url = kwargs.get('base_url', None)

            # Configure with optional base_url
            if base_url:
                # Use client_options to set custom endpoint
                from google.api_core.client_options import ClientOptions
                client_options = ClientOptions(api_endpoint=base_url)
                genai.configure(api_key=api_key, client_options=client_options)
            else:
                genai.configure(api_key=api_key)

            self.genai = genai
            self.client = genai.GenerativeModel(model)
        except ImportError:
            raise ImportError(
                "Google Generative AI package not installed. "
                "Install with: pip install google-generativeai"
            )

    @with_retry()
    def _make_api_call(self, model, messages, tools, generation_config):
        """Internal method to make API call with retry logic."""
        if tools:
            return model.generate_content(
                messages,
                tools=tools,
                generation_config=generation_config
            )
        else:
            return model.generate_content(
                messages,
                generation_config=generation_config
            )

    def call(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        **kwargs
    ) -> LLMResponse:
        """Call Gemini API with automatic retry on rate limits.

        Args:
            messages: List of conversation messages
            tools: Optional list of tool schemas
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters (temperature, etc.)

        Returns:
            LLMResponse with unified format
        """
        # Convert messages to Gemini format
        gemini_messages = []
        system_instruction = None

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                gemini_messages.append({
                    "role": "user",
                    "parts": [{"text": str(msg.content)}]
                })
            elif msg.role == "assistant":
                # Handle assistant messages
                if isinstance(msg.content, str):
                    gemini_messages.append({
                        "role": "model",
                        "parts": [{"text": msg.content}]
                    })
                else:
                    # Handle content blocks
                    parts = []
                    for block in msg.content:
                        # Safely check if block has text
                        try:
                            if hasattr(block, "text") and block.text:
                                parts.append({"text": block.text})
                        except (ValueError, AttributeError):
                            # Skip blocks that aren't text (e.g., function_call)
                            pass
                    if parts:
                        gemini_messages.append({
                            "role": "model",
                            "parts": parts
                        })

        # Convert tools to Gemini format if provided
        gemini_tools = None
        if tools:
            gemini_functions = []
            for tool in tools:
                gemini_functions.append({
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"]
                })
            gemini_tools = [{"function_declarations": gemini_functions}]

        # Prepare generation config
        generation_config = {
            "max_output_tokens": max_tokens,
        }
        generation_config.update(kwargs)

        # Create model with system instruction if provided
        model = self.client
        if system_instruction:
            model = self.genai.GenerativeModel(
                self.model,
                system_instruction=system_instruction
            )

        # Make API call with retry logic
        try:
            response = self._make_api_call(
                model,
                gemini_messages,
                gemini_tools,
                generation_config
            )

            # Log token usage
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                logger.debug(f"Token Usage: Input={usage.prompt_token_count}, Output={usage.candidates_token_count}, Total={usage.total_token_count}")

            # Determine stop reason
            if hasattr(response, "candidates") and response.candidates:
                finish_reason = response.candidates[0].finish_reason
                # Check for function calls
                has_function_call = False
                try:
                    if hasattr(response.candidates[0].content, "parts"):
                        has_function_call = any(
                            hasattr(part, "function_call")
                            for part in response.candidates[0].content.parts
                        )
                except (ValueError, AttributeError):
                    pass

                if has_function_call:
                    stop_reason = "tool_use"
                elif finish_reason == 1:  # STOP
                    stop_reason = "end_turn"
                elif finish_reason == 2:  # MAX_TOKENS
                    stop_reason = "max_tokens"
                else:
                    stop_reason = "end_turn"
            else:
                stop_reason = "end_turn"

            # Extract token usage
            usage_dict = None
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                usage_dict = {
                    "input_tokens": usage.prompt_token_count,
                    "output_tokens": usage.candidates_token_count
                }

            return LLMResponse(
                content=response,
                stop_reason=stop_reason,
                raw_response=response,
                usage=usage_dict
            )

        except Exception as e:
            raise RuntimeError(f"Gemini API call failed: {str(e)}")

    def extract_text(self, response: LLMResponse) -> str:
        """Extract text from Gemini response.

        Args:
            response: LLMResponse object

        Returns:
            Extracted text
        """
        try:
            return response.content.text
        except:
            return ""

    def extract_tool_calls(self, response: LLMResponse) -> List[ToolCall]:
        """Extract tool calls from Gemini response.

        Args:
            response: LLMResponse object

        Returns:
            List of ToolCall objects
        """
        tool_calls = []

        try:
            if hasattr(response.content, "candidates"):
                for candidate in response.content.candidates:
                    if hasattr(candidate.content, "parts"):
                        for part in candidate.content.parts:
                            if hasattr(part, "function_call"):
                                fc = part.function_call
                                # Convert arguments to dict
                                args = {}
                                if hasattr(fc, "args"):
                                    for key, value in fc.args.items():
                                        args[key] = value

                                tool_calls.append(ToolCall(
                                    id=f"call_{fc.name}",  # Gemini doesn't provide IDs
                                    name=fc.name,
                                    arguments=args
                                ))
        except:
            pass

        return tool_calls

    def format_tool_results(self, results: List[ToolResult]) -> LLMMessage:
        """Format tool results for Gemini.

        Args:
            results: List of tool results

        Returns:
            LLMMessage with formatted results
        """
        # Gemini expects tool results in a specific format
        # For simplicity, we'll format as text
        combined_content = "\n\n".join([
            f"Tool result: {result.content}"
            for result in results
        ])

        return LLMMessage(role="user", content=combined_content)

    @property
    def supports_tools(self) -> bool:
        """Gemini supports function calling."""
        return True
