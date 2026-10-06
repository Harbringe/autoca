"""Writing one row per model call. Best effort: a failure here must never break the work being measured."""

from __future__ import annotations

import logging

from django.db import transaction

from usage.models import Outcome, UsageEvent
from usage.pricing import cost_micro_usd

logger = logging.getLogger("autoca.usage")


def record(
    *,
    purpose: str,
    model: str = "",
    response=None,
    outcome: str = Outcome.OK,
    firm_id=None,
    client_id=None,
    latency_ms: int = 0,
    rows: int = 0,
    pages: int = 0,
) -> None:
    """Record one call. ``response`` is the adapter's reply (its token counts and model are used) or None for a failure."""
    try:
        input_tokens = int(getattr(response, "input_tokens", 0) or 0)
        cached_tokens = int(getattr(response, "cached_tokens", 0) or 0)
        output_tokens = int(getattr(response, "output_tokens", 0) or 0)
        name = (getattr(response, "model", "") or model or "")[:80]
        cost, priced = cost_micro_usd(name, input_tokens, cached_tokens, output_tokens)
        # Its own savepoint, so a failure to write leaves the caller's transaction usable.
        with transaction.atomic():
            UsageEvent.objects.create(
                purpose=purpose,
                model=name,
                outcome=outcome,
                firm_id=firm_id,
                client_id=client_id,
                input_tokens=input_tokens,
                cached_tokens=cached_tokens,
                output_tokens=output_tokens,
                latency_ms=max(int(latency_ms), 0),
                rows=max(int(rows), 0),
                pages=max(int(pages), 0),
                cost_micro_usd=cost,
                priced=priced,
            )
    except Exception:  # noqa: BLE001 -- measuring must never break the work
        logger.warning("could not record model usage", exc_info=True)
