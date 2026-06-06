"""Observability configuration — env vars, model pricing, and cost granularity."""

import os
from enum import Enum


# ---------------------------------------------------------------------------
# Cost-tracking granularity
# ---------------------------------------------------------------------------

class CostGranularity(Enum):
    """Controls how cost is aggregated and reported."""
    SESSION = "session"       # per ADK session (default)
    TURN = "turn"             # per user→agent turn
    CUMULATIVE = "cumulative" # running total across all sessions


def _parse_granularity(raw: str) -> CostGranularity:
    try:
        return CostGranularity(raw.strip().lower())
    except ValueError:
        return CostGranularity.SESSION


# ---------------------------------------------------------------------------
# Environment knobs
# ---------------------------------------------------------------------------

TRACE_TO_CLOUD: bool = os.getenv("TRACE_TO_CLOUD", "false").lower() == "true"
LOG_LLM_CONTENT: bool = os.getenv("LOG_LLM_CONTENT", "true").lower() == "true"
COST_GRANULARITY: CostGranularity = _parse_granularity(
    os.getenv("COST_GRANULARITY", "session")
)

# ---------------------------------------------------------------------------
# Gemini 2.5 Flash pricing (USD per 1 M tokens, as of June 2025)
# Source: https://ai.google.dev/pricing
# Update these when pricing changes or swap for Pricing API lookup.
# ---------------------------------------------------------------------------

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Map of model-name → (input_price_per_1m, output_price_per_1m)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro":   (1.25, 10.00),
    "gemini-2.0-flash":  (0.10, 0.40),
}

# Fallback for unknown models
DEFAULT_PRICING: tuple[float, float] = (0.30, 2.50)


def get_pricing(model: str) -> tuple[float, float]:
    """Return ``(input_price_per_1m, output_price_per_1m)`` for *model*."""
    return MODEL_PRICING.get(model, DEFAULT_PRICING)
