"""Token counting and cost tracking for memory management."""

import logging
from typing import Dict

from llm.base import LLMMessage
from utils.model_pricing import MODEL_PRICING

logger = logging.getLogger(__name__)


class TokenTracker:
    """Tracks token usage and costs across conversations."""

    # Use imported pricing configuration
    PRICING = MODEL_PRICING

    def __init__(self):
        """Initialize token tracker."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.compression_savings = 0  # Tokens saved through compression
        self.compression_cost = 0  # Tokens spent on compression

    def count_message_tokens(self, message: LLMMessage, provider: str, model: str) -> int:
        """Count tokens in a message.

        Args:
            message: LLMMessage to count tokens for
            provider: LLM provider name ("openai", "anthropic", "gemini")
            model: Model identifier

        Returns:
            Token count
        """
        content = self._extract_content(message)

        if provider == "openai":
            return self._count_openai_tokens(content, model)
        elif provider == "anthropic":
            return self._count_anthropic_tokens(content)
        elif provider == "gemini":
            return self._count_gemini_tokens(content)
        else:
            # Fallback: rough estimate
            return len(str(content)) // 4

    def _extract_content(self, message) -> str:
        """Extract text content from message."""
        content = message.content

        # Handle different content formats
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Content blocks (Anthropic format)
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        # Include tool use in token count
                        text_parts.append(str(block))
                    elif block.get("type") == "tool_result":
                        # Include tool results in token count
                        text_parts.append(str(block))
            return "\n".join(text_parts)
        else:
            return str(content)

    def _count_openai_tokens(self, text: str, model: str) -> int:
        """Count tokens using tiktoken for OpenAI models."""
        try:
            import tiktoken

            try:
                encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to cl100k_base for unknown models
                encoding = tiktoken.get_encoding("cl100k_base")

            return len(encoding.encode(text))
        except ImportError:
            logger.warning("tiktoken not installed, using fallback estimation")
            return len(text) // 4
        except Exception as e:
            logger.warning(f"Error counting tokens: {e}, using fallback")
            return len(text) // 4

    def _count_anthropic_tokens(self, text: str) -> int:
        """Count tokens for Anthropic models.

        Note: Anthropic SDK no longer provides a direct token counting method.
        Using estimation: ~3.5 characters per token (based on Claude's tokenizer).
        """
        # Anthropic's rough estimation: 1 token ≈ 3.5 characters
        # This is more accurate than 4 chars/token for Claude models
        return int(len(text) / 3.5) if len(text) > 0 else 0

    def _count_gemini_tokens(self, text: str) -> int:
        """Estimate tokens for Gemini models.

        Note: Google doesn't provide a token counting API for Gemini,
        so we use an approximation.
        """
        # Rough estimate: 1 token ≈ 4 characters
        return len(text) // 4

    def add_input_tokens(self, count: int):
        """Record input tokens used."""
        self.total_input_tokens += count

    def add_output_tokens(self, count: int):
        """Record output tokens generated."""
        self.total_output_tokens += count

    def add_compression_savings(self, saved: int):
        """Record tokens saved through compression."""
        self.compression_savings += saved

    def add_compression_cost(self, cost: int):
        """Record tokens spent on compression."""
        self.compression_cost += cost

    def calculate_cost(
        self, model: str, input_tokens: int = None, output_tokens: int = None
    ) -> float:
        """Calculate cost for given token usage.

        Args:
            model: Model identifier
            input_tokens: Input token count (None = use total)
            output_tokens: Output token count (None = use total)

        Returns:
            Cost in USD
        """
        if input_tokens is None:
            input_tokens = self.total_input_tokens
        if output_tokens is None:
            output_tokens = self.total_output_tokens

        # Find matching pricing
        pricing = None
        for model_key, price in self.PRICING.items():
            if model_key in model:
                pricing = price
                break

        if not pricing:
            logger.info(
                f"No pricing found for model {model}, using default pricing (DeepSeek-Reasoner equivalent)"
            )
            # Fallback to default pricing (using reasonable mid-tier estimate)
            pricing = self.PRICING["default"]

        # Calculate cost
        input_cost = (input_tokens * pricing["input"]) / 1_000_000
        output_cost = (output_tokens * pricing["output"]) / 1_000_000

        return input_cost + output_cost

    def get_total_cost(self, model: str) -> float:
        """Get total cost for this conversation.

        Args:
            model: Model identifier

        Returns:
            Total cost in USD
        """
        return self.calculate_cost(model)

    def get_net_savings(self, model: str) -> Dict[str, float]:
        """Calculate net token and cost savings after accounting for compression overhead.

        Args:
            model: Model identifier

        Returns:
            Dict with net_tokens, net_cost, savings_percentage
        """
        net_tokens = self.compression_savings - self.compression_cost

        # Calculate cost of saved tokens
        saved_cost = self.calculate_cost(
            model, input_tokens=self.compression_savings, output_tokens=0
        )
        compression_cost = self.calculate_cost(
            model, input_tokens=0, output_tokens=self.compression_cost
        )
        net_cost = saved_cost - compression_cost

        # Calculate percentage
        total_tokens = self.total_input_tokens + self.total_output_tokens
        savings_percentage = (net_tokens / total_tokens * 100) if total_tokens > 0 else 0

        return {
            "net_tokens": net_tokens,
            "net_cost": net_cost,
            "savings_percentage": savings_percentage,
            "total_saved_tokens": self.compression_savings,
            "compression_overhead_tokens": self.compression_cost,
        }

    def get_budget_status(self, max_tokens: int) -> Dict:
        """Get current usage vs budget.

        Args:
            max_tokens: Maximum token budget

        Returns:
            Dict with usage statistics
        """
        total_tokens = self.total_input_tokens + self.total_output_tokens
        percentage = (total_tokens / max_tokens * 100) if max_tokens > 0 else 0

        return {
            "total_tokens": total_tokens,
            "max_tokens": max_tokens,
            "percentage": percentage,
            "remaining": max(0, max_tokens - total_tokens),
            "over_budget": total_tokens > max_tokens,
        }

    def reset(self):
        """Reset all counters."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.compression_savings = 0
        self.compression_cost = 0
