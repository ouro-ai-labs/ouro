"""Token counting and cost tracking for memory management."""

import logging
from typing import Dict

from llm.content_utils import extract_text
from llm.message_types import LLMMessage
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
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0
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
        """Extract text content from message.

        Uses centralized extract_text from content_utils.
        """
        # Use centralized extraction
        text = extract_text(message.content)

        # For token counting, also include tool calls as string representation
        if hasattr(message, "tool_calls") and message.tool_calls:
            text += "\n" + str(message.tool_calls)

        return text if text else str(message.content)

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

    def add_cache_read_tokens(self, count: int):
        """Record cache read (hit) tokens."""
        self.total_cache_read_tokens += count

    def add_cache_creation_tokens(self, count: int):
        """Record cache creation (write) tokens."""
        self.total_cache_creation_tokens += count

    def add_compression_savings(self, saved: int):
        """Record tokens saved through compression."""
        self.compression_savings += saved

    def add_compression_cost(self, cost: int):
        """Record tokens spent on compression."""
        self.compression_cost += cost

    def _find_pricing(self, model: str) -> dict:
        """Find pricing entry for a model using longest substring match.

        When multiple keys match (e.g. both "claude-sonnet-4" and
        "claude-sonnet-4-5" match "anthropic/claude-sonnet-4-5-20250929"),
        the longest key wins so ordering in MODEL_PRICING doesn't matter.

        Args:
            model: Model identifier

        Returns:
            Pricing dict with at least 'input' and 'output' keys
        """
        best_key = ""
        best_pricing = None
        for model_key, price in self.PRICING.items():
            if model_key != "default" and model_key in model and len(model_key) > len(best_key):
                best_key = model_key
                best_pricing = price

        if best_pricing:
            return best_pricing

        logger.info(
            f"No pricing found for model {model}, using default pricing (DeepSeek-Reasoner equivalent)"
        )
        return self.PRICING["default"]

    def calculate_cost(
        self, model: str, input_tokens: int = None, output_tokens: int = None
    ) -> float:
        """Calculate cost for given token usage (without cache adjustments).

        Used for hypothetical cost calculations (e.g. compression savings).
        For actual conversation cost, use get_total_cost() which accounts for cache pricing.

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

        pricing = self._find_pricing(model)

        input_cost = (input_tokens * pricing["input"]) / 1_000_000
        output_cost = (output_tokens * pricing["output"]) / 1_000_000

        return input_cost + output_cost

    def get_total_cost(self, model: str) -> float:
        """Get total cost for this conversation, accounting for cache token pricing.

        Cache read tokens are cheaper than regular input (e.g. 0.1× for Anthropic).
        Cache write tokens may be more expensive (e.g. 1.25× for Anthropic).
        Non-cached input tokens are priced at the standard input rate.

        Args:
            model: Model identifier

        Returns:
            Total cost in USD
        """
        pricing = self._find_pricing(model)

        cache_read_price = pricing.get("cache_read", pricing["input"])
        cache_write_price = pricing.get("cache_write", pricing["input"])

        non_cached_input = max(
            0,
            self.total_input_tokens
            - self.total_cache_read_tokens
            - self.total_cache_creation_tokens,
        )

        input_cost = (non_cached_input * pricing["input"]) / 1_000_000
        cache_read_cost = (self.total_cache_read_tokens * cache_read_price) / 1_000_000
        cache_write_cost = (self.total_cache_creation_tokens * cache_write_price) / 1_000_000
        output_cost = (self.total_output_tokens * pricing["output"]) / 1_000_000

        return input_cost + cache_read_cost + cache_write_cost + output_cost

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

    def reset(self):
        """Reset all counters."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0
        self.compression_savings = 0
        self.compression_cost = 0
