"""Token counting and cost tracking for memory management."""
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class TokenTracker:
    """Tracks token usage and costs across conversations."""

    # Pricing per 1M tokens (Updated Jan 2026)
    PRICING = {
        # --- OpenAI ---
        "gpt-5": {"input": 1.25, "output": 10.00},          # 新一代旗舰，兼顾性能与成本
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "o1": {"input": 15.00, "output": 60.00},            # 高级逻辑推理
        "o1-mini": {"input": 1.10, "output": 4.40},
        "o3": {"input": 2.00, "output": 8.00},              # 最新实时推理模型
        "o3-mini": {"input": 0.40, "output": 1.60},

        # --- Anthropic ---
        "claude-4-5-opus": {"input": 5.00, "output": 25.00},   # 2025年底降价后的新价格
        "claude-4-5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-4-5-haiku": {"input": 1.00, "output": 5.00},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},

        # --- Google Gemini ---
        "gemini-3-pro": {"input": 2.00, "output": 12.00},   # 最新 Gemini 3 系列
        "gemini-3-flash": {"input": 0.50, "output": 3.00},
        "gemini-2-5-pro": {"input": 1.25, "output": 10.00},
        "gemini-2-5-flash": {"input": 0.30, "output": 2.50},
        "gemini-1-5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1-5-flash": {"input": 0.075, "output": 0.30},

        # --- DeepSeek (极高性价比) ---
        "deepseek-v3": {"input": 0.14, "output": 0.28},     # 命中缓存时 input 低至 0.01
        "deepseek-reasoner": {"input": 0.55, "output": 2.19}, # 对应 R1 系列

        # --- xAI (Grok) ---
        "grok-4": {"input": 3.00, "output": 15.00},
        "grok-4-fast": {"input": 0.20, "output": 0.50},

        # --- Mistral ---
        "mistral-large-2": {"input": 2.00, "output": 6.00},
        "mistral-small-3": {"input": 0.10, "output": 0.30},

        "default": {"input": 0.55, "output": 2.19},
    }

    def __init__(self):
        """Initialize token tracker."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.compression_savings = 0  # Tokens saved through compression
        self.compression_cost = 0  # Tokens spent on compression

    def count_message_tokens(self, message: "LLMMessage", provider: str, model: str) -> int:
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

    def calculate_cost(self, model: str, input_tokens: int = None, output_tokens: int = None) -> float:
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
            logger.warning(f"No pricing found for model {model}, returning 0")
            # Fallback to default pricing
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
        saved_cost = self.calculate_cost(model, input_tokens=self.compression_savings, output_tokens=0)
        compression_cost = self.calculate_cost(model, input_tokens=0, output_tokens=self.compression_cost)
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
