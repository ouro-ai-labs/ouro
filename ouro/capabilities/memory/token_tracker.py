"""Token counting and cost tracking for memory management."""

import hashlib
import json
import logging
from typing import Dict

import litellm

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
        self._token_cache: Dict[str, int] = {}

    def count_message_tokens(self, message: LLMMessage, provider: str, model: str) -> int:
        """Count tokens in a message using litellm.token_counter.

        Args:
            message: LLMMessage to count tokens for
            provider: LLM provider name (kept for API compat, not used for routing)
            model: Model identifier

        Returns:
            Token count
        """
        cache_key = self._make_cache_key(message)
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        try:
            msg_dict = message.to_dict()
            count = litellm.token_counter(model=model, messages=[msg_dict])
        except Exception as e:
            logger.debug(f"litellm.token_counter failed ({e}), using fallback")
            content = self._extract_content_text(message)
            count = max(1, len(content) // 4)

        self._token_cache[cache_key] = count
        return count

    def _make_cache_key(self, message: LLMMessage) -> str:
        """Build a content-based cache key for a message."""
        parts = [message.role, str(message.content or "")]
        if message.tool_calls:
            parts.append(json.dumps(message.tool_calls, sort_keys=True))
        if message.tool_call_id:
            parts.append(message.tool_call_id)
        if message.name:
            parts.append(message.name)
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _extract_content_text(message: LLMMessage) -> str:
        """Fallback: extract plain text from a message for rough estimation."""
        from llm.content_utils import extract_text

        text = extract_text(message.content)
        if hasattr(message, "tool_calls") and message.tool_calls:
            text += "\n" + str(message.tool_calls)
        return text if text else str(message.content)

    def record_usage(self, usage: Dict[str, int]) -> None:
        """Record token usage from an LLM response in one call.

        Accepts the usage dict produced by LiteLLMAdapter._convert_response().

        Args:
            usage: Dict with keys input_tokens, output_tokens, and optionally
                   cache_read_tokens, cache_creation_tokens.
        """
        self.total_input_tokens += usage.get("input_tokens", 0)
        self.total_output_tokens += usage.get("output_tokens", 0)
        self.total_cache_read_tokens += usage.get("cache_read_tokens", 0)
        self.total_cache_creation_tokens += usage.get("cache_creation_tokens", 0)

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

        Cache read tokens are cheaper than regular input (e.g. 0.1x for Anthropic).
        Cache write tokens may be more expensive (e.g. 1.25x for Anthropic).
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
        self._token_cache.clear()
