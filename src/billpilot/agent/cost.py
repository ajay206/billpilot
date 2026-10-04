"""Token prices and a labelled estimate for one eval run.

Prices are USD per million tokens. The fake model is priced at zero so CI
does not pretend to spend money. Override the table with LLM_PRICE_TABLE.
"""

import json
from decimal import Decimal

from billpilot.config import Settings

# Published list prices for the default cheap chat model, as of this phase.
# They are configuration, not a bill. A provider can charge something else.
DEFAULT_PRICE_TABLE: dict[str, dict[str, str]] = {
    "gpt-4o-mini": {"prompt_per_million": "0.15", "completion_per_million": "0.60"},
    "fake": {"prompt_per_million": "0", "completion_per_million": "0"},
    "scripted": {"prompt_per_million": "0", "completion_per_million": "0"},
}

# Assumptions for the estimate printed before a real run. Not a measurement.
ESTIMATE_CALLS_PER_CASE = 3
ESTIMATE_PROMPT_TOKENS_PER_CALL = 1200
ESTIMATE_COMPLETION_TOKENS_PER_CALL = 350


def price_table(settings: Settings) -> dict[str, dict[str, Decimal]]:
    raw = json.loads(json.dumps(DEFAULT_PRICE_TABLE))
    raw["default"] = {
        "prompt_per_million": settings.llm_prompt_price_per_million,
        "completion_per_million": settings.llm_completion_price_per_million,
    }
    if settings.llm_price_table.strip():
        raw.update(json.loads(settings.llm_price_table))
    parsed: dict[str, dict[str, Decimal]] = {}
    for name, row in raw.items():
        parsed[name] = {
            "prompt_per_million": Decimal(str(row["prompt_per_million"])),
            "completion_per_million": Decimal(str(row["completion_per_million"])),
        }
    return parsed


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int, settings: Settings) -> Decimal:
    table = price_table(settings)
    prices = table.get(model) or table["default"]
    prompt = Decimal(prompt_tokens) * prices["prompt_per_million"] / Decimal(1_000_000)
    completion = Decimal(completion_tokens) * prices["completion_per_million"] / Decimal(1_000_000)
    return (prompt + completion).quantize(Decimal("0.000001"))


def estimate_eval_run_usd(case_count: int, settings: Settings, model: str | None = None) -> Decimal:
    """What one full eval would cost at the configured prices. This is an estimate."""
    name = model or settings.llm_model
    per_call = estimate_cost(
        name,
        ESTIMATE_PROMPT_TOKENS_PER_CALL,
        ESTIMATE_COMPLETION_TOKENS_PER_CALL,
        settings,
    )
    return (per_call * ESTIMATE_CALLS_PER_CASE * case_count).quantize(Decimal("0.000001"))
