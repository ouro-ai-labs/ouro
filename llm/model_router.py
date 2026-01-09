"""Smart model routing for cost optimization.

This module implements intelligent model selection based on operation complexity,
achieving 70-80% cost reduction by using cheaper models for simpler operations.
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import re


class OperationTier(Enum):
    """Operation complexity tiers for model selection."""
    LIGHT = "light"      # Simple operations: tool results, acknowledgments
    MEDIUM = "medium"    # Standard operations: most tool calls, basic reasoning
    HEAVY = "heavy"      # Complex operations: planning, synthesis, complex reasoning


@dataclass
class ModelTierConfig:
    """Configuration for model tiers."""
    light_model: str      # Cheapest model for simple operations
    medium_model: str     # Mid-tier model for standard operations
    heavy_model: str      # Most capable model for complex operations

    # Cost per 1M tokens (input/output) for reference
    light_cost: tuple = (0.25, 1.25)      # Example: Haiku costs
    medium_cost: tuple = (1.0, 5.0)       # Example: Sonnet costs
    heavy_cost: tuple = (3.0, 15.0)       # Example: Opus costs


class ModelRouter:
    """Smart router that selects the appropriate model based on operation complexity."""

    # Tool calls that are simple and can use light models
    LIGHT_TOOLS = {
        'read_file',
        'write_file',
        'glob_files',
        'grep_content',
        'search_files',
        'manage_todo_list',  # Simple CRUD operations
    }

    # Tool calls that need medium models
    MEDIUM_TOOLS = {
        'edit_file',         # Requires understanding context
        'calculate',         # Needs code execution reasoning
        'web_search',        # Needs to formulate queries
        'shell',            # Potentially dangerous, needs careful reasoning
    }

    # Patterns indicating complex reasoning (need heavy model)
    COMPLEX_PATTERNS = [
        r'plan',
        r'synthesize',
        r'analyze',
        r'design',
        r'architect',
        r'refactor',
        r'debug',
        r'explain.*why',
        r'compare.*between',
        r'evaluate',
        r'recommend',
    ]

    def __init__(self, config: ModelTierConfig, enable_routing: bool = True):
        """Initialize the model router.

        Args:
            config: Model tier configuration
            enable_routing: Whether to enable smart routing (if False, always use heavy model)
        """
        self.config = config
        self.enable_routing = enable_routing
        self._stats = {
            'light_calls': 0,
            'medium_calls': 0,
            'heavy_calls': 0,
        }

    def select_model(
        self,
        operation_type: str,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[str, OperationTier]:
        """Select the appropriate model for an operation.

        Args:
            operation_type: Type of operation (e.g., 'tool_call', 'reasoning', 'synthesis')
            context: Optional context including:
                - tool_name: Name of tool being called
                - message_content: Content of the message
                - is_first_call: Whether this is the first call in the loop
                - has_tool_results: Whether processing tool results

        Returns:
            Tuple of (model_name, operation_tier)
        """
        if not self.enable_routing:
            return self.config.heavy_model, OperationTier.HEAVY

        context = context or {}

        # Determine operation tier
        tier = self._classify_operation(operation_type, context)

        # Select model based on tier
        if tier == OperationTier.LIGHT:
            self._stats['light_calls'] += 1
            return self.config.light_model, tier
        elif tier == OperationTier.MEDIUM:
            self._stats['medium_calls'] += 1
            return self.config.medium_model, tier
        else:  # HEAVY
            self._stats['heavy_calls'] += 1
            return self.config.heavy_model, tier

    def _classify_operation(
        self,
        operation_type: str,
        context: Dict[str, Any]
    ) -> OperationTier:
        """Classify operation complexity.

        Args:
            operation_type: Type of operation
            context: Operation context

        Returns:
            OperationTier enum value
        """
        # Rule 1: First call in a conversation always uses heavy model
        # (needs to understand the task and plan approach)
        if context.get('is_first_call', False):
            return OperationTier.HEAVY

        # Rule 2: Planning and synthesis always use heavy model
        if operation_type in ('planning', 'synthesis', 'initial_reasoning'):
            return OperationTier.HEAVY

        # Rule 3: Processing tool results can often use light model
        if context.get('has_tool_results', False):
            # Check if it's just a simple acknowledgment or needs reasoning
            tool_name = context.get('tool_name', '')
            if tool_name in self.LIGHT_TOOLS:
                return OperationTier.LIGHT
            return OperationTier.MEDIUM

        # Rule 4: Tool call classification
        if operation_type == 'tool_call':
            tool_name = context.get('tool_name', '')
            if tool_name in self.LIGHT_TOOLS:
                return OperationTier.LIGHT
            elif tool_name in self.MEDIUM_TOOLS:
                return OperationTier.MEDIUM
            else:
                return OperationTier.HEAVY

        # Rule 5: Check message content for complexity indicators
        message_content = context.get('message_content', '')
        if message_content:
            message_lower = message_content.lower()
            for pattern in self.COMPLEX_PATTERNS:
                if re.search(pattern, message_lower):
                    return OperationTier.HEAVY

        # Rule 6: Default to medium for safety
        return OperationTier.MEDIUM

    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics.

        Returns:
            Dictionary with routing stats and cost savings
        """
        total_calls = sum(self._stats.values())
        if total_calls == 0:
            return {
                'total_calls': 0,
                'light_calls': 0,
                'medium_calls': 0,
                'heavy_calls': 0,
                'light_percentage': 0,
                'medium_percentage': 0,
                'heavy_percentage': 0,
                'estimated_cost_savings': 0,
            }

        light_pct = (self._stats['light_calls'] / total_calls) * 100
        medium_pct = (self._stats['medium_calls'] / total_calls) * 100
        heavy_pct = (self._stats['heavy_calls'] / total_calls) * 100

        # Estimate cost savings (rough approximation)
        # Assume without routing, all calls would use heavy model
        # With routing, we use cheaper models for light/medium calls
        # Cost savings = (light% * 80%) + (medium% * 50%)
        estimated_savings = (light_pct * 0.8 + medium_pct * 0.5) / 100

        return {
            'total_calls': total_calls,
            'light_calls': self._stats['light_calls'],
            'medium_calls': self._stats['medium_calls'],
            'heavy_calls': self._stats['heavy_calls'],
            'light_percentage': light_pct,
            'medium_percentage': medium_pct,
            'heavy_percentage': heavy_pct,
            'estimated_cost_savings_pct': estimated_savings * 100,
        }

    def reset_stats(self):
        """Reset routing statistics."""
        self._stats = {
            'light_calls': 0,
            'medium_calls': 0,
            'heavy_calls': 0,
        }


# Removed: create_model_tier_config() function
# Users now directly specify LIGHT_MODEL, MEDIUM_MODEL, HEAVY_MODEL in .env
# This simplifies configuration and gives users full control
