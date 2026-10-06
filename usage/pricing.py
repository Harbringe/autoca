"""The price of a call, from a table in settings.

``LLM_PRICES`` maps a model name to US dollars per million tokens for three kinds: ``input`` (ordinary), ``cached`` (input the
provider served from its cache) and ``output``. Amounts are kept as whole millionths of a dollar so they add up exactly.
A model with no entry costs nothing here and is marked unpriced, so the admin can say "unknown" rather than "free".
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

MICRO = 1_000_000


def prices(model: str) -> dict | None:
    table = getattr(settings, "LLM_PRICES", {}) or {}
    return table.get(model)


def cost_micro_usd(
    model: str, input_tokens: int, cached_tokens: int, output_tokens: int
) -> tuple[int, bool]:
    """``(millionths of a dollar, priced)`` for one call. Cached tokens are part of the input and billed at their own rate."""
    entry = prices(model)
    if not entry:
        return 0, False
    cached = min(max(cached_tokens, 0), max(input_tokens, 0))
    fresh = max(input_tokens, 0) - cached
    # tokens x (dollars per million) is exactly millionths of a dollar.
    total = (
        Decimal(fresh) * Decimal(str(entry.get("input", 0)))
        + Decimal(cached) * Decimal(str(entry.get("cached", entry.get("input", 0))))
        + Decimal(max(output_tokens, 0)) * Decimal(str(entry.get("output", 0)))
    )
    return int(total.to_integral_value()), True


def usd(micro: int) -> Decimal:
    return Decimal(micro) / MICRO


def inr(micro: int) -> Decimal:
    """A rupee estimate at the rate in ``USD_INR_RATE``. An estimate: the card's own rate and fees are not in it."""
    return usd(micro) * Decimal(str(getattr(settings, "USD_INR_RATE", 90)))
