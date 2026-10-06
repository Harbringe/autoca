"""The figures the platform owner reads at the top of the usage page. All from the recorded calls, computed on request."""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from usage.models import Outcome, Purpose, UsageEvent
from usage.pricing import inr, usd

DAYS = 30
TOP_FIRMS = 10


def _totals(events) -> dict:
    row = events.aggregate(
        calls=Count("id"),
        answered=Count("id", filter=Q(outcome=Outcome.OK)),
        rate_limited=Count("id", filter=Q(outcome=Outcome.RATE_LIMITED)),
        failed=Count("id", filter=Q(outcome=Outcome.ERROR)),
        unpriced=Count("id", filter=Q(priced=False)),
        input_tokens=Sum("input_tokens"),
        cached_tokens=Sum("cached_tokens"),
        output_tokens=Sum("output_tokens"),
        rows=Sum("rows"),
        pages=Sum("pages"),
        cost=Sum("cost_micro_usd"),
        latency=Avg("latency_ms", filter=Q(outcome=Outcome.OK)),
    )
    cost = int(row["cost"] or 0)
    input_tokens = int(row["input_tokens"] or 0)
    cached = int(row["cached_tokens"] or 0)
    calls = int(row["calls"] or 0)
    rows = int(row["rows"] or 0)
    return {
        "calls": calls,
        "answered": int(row["answered"] or 0),
        "rate_limited": int(row["rate_limited"] or 0),
        "failed": int(row["failed"] or 0),
        "unpriced": int(row["unpriced"] or 0),
        "input_tokens": input_tokens,
        "cached_tokens": cached,
        "output_tokens": int(row["output_tokens"] or 0),
        "rows": rows,
        "pages": int(row["pages"] or 0),
        "cost_micro": cost,
        "cost_usd": usd(cost),
        "cost_inr": inr(cost),
        # Of the input, the share the provider served from cache. None when there was no input.
        "cache_hit_percent": round(cached * 100 / input_tokens) if input_tokens else None,
        "error_percent": round((row["failed"] or 0) * 100 / calls) if calls else None,
        "avg_latency_ms": int(row["latency"] or 0),
        # Cost per row the model was asked about, in US dollars. None when no rows were recorded.
        "usd_per_row": (usd(cost) / rows) if rows else None,
    }


def _firm_names(ids) -> dict:
    """Firm names for the ids, from the platform's own read-only view. Empty if it cannot be read."""
    try:
        from superadmin.models import PlatformFirm

        return {str(f.pk): f.name for f in PlatformFirm.objects.filter(pk__in=list(ids))}
    except Exception:  # noqa: BLE001 -- the names are a convenience; the figures stand without them
        return {}


def summary(now: datetime.datetime | None = None) -> dict:
    now = now or timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    window_start = today_start - datetime.timedelta(days=DAYS - 1)

    events = UsageEvent.objects.all()
    month = events.filter(at__gte=month_start)

    daily_rows = {
        r["day"]: r
        for r in events.filter(at__gte=window_start)
        .annotate(day=TruncDate("at"))
        .values("day")
        .annotate(calls=Count("id"), cost=Sum("cost_micro_usd"))
    }
    days = [window_start.date() + datetime.timedelta(days=i) for i in range(DAYS)]
    peak = max((int(r["cost"] or 0) for r in daily_rows.values()), default=0)
    daily = [
        {
            "date": d,
            "calls": int(daily_rows[d]["calls"]) if d in daily_rows else 0,
            "cost_micro": int(daily_rows[d]["cost"] or 0) if d in daily_rows else 0,
            "cost_usd": usd(int(daily_rows[d]["cost"] or 0)) if d in daily_rows else Decimal(0),
            "percent_of_peak": round(int(daily_rows[d]["cost"] or 0) * 100 / peak)
            if d in daily_rows and peak
            else 0,
        }
        for d in days
    ]

    purposes = [
        {
            "label": Purpose(p["purpose"]).label
            if p["purpose"] in Purpose.values
            else p["purpose"],
            **_totals(month.filter(purpose=p["purpose"])),
        }
        for p in month.values("purpose").distinct().order_by("purpose")
    ]

    top = list(
        month.exclude(firm_id=None)
        .values("firm_id")
        .annotate(cost=Sum("cost_micro_usd"), calls=Count("id"))
        .order_by("-cost")[:TOP_FIRMS]
    )
    names = _firm_names([t["firm_id"] for t in top])
    firms = [
        {
            "firm_id": str(t["firm_id"]),
            "name": names.get(str(t["firm_id"]), f"Firm {str(t['firm_id'])[:8]}"),
            "calls": t["calls"],
            "cost_usd": usd(int(t["cost"] or 0)),
            "cost_inr": inr(int(t["cost"] or 0)),
        }
        for t in top
    ]

    month_totals = _totals(month)
    budget = Decimal(str(getattr(settings, "LLM_MONTHLY_BUDGET_USD", 0) or 0))
    return {
        "as_of": now,
        "today": _totals(events.filter(at__gte=today_start)),
        "month": month_totals,
        "daily": daily,
        "by_purpose": purposes,
        "by_firm": firms,
        "budget_usd": budget,
        "budget_used_percent": min(round(month_totals["cost_usd"] * 100 / budget), 100)
        if budget
        else None,
        "budget_over": bool(budget) and month_totals["cost_usd"] > budget,
        "usd_inr": Decimal(str(getattr(settings, "USD_INR_RATE", 90))),
    }
