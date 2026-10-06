"""The figures the platform owner reads at the top of the usage page. All from the recorded calls, computed on request."""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from usage import charts
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


# ---------------------------------------------------------------------------
# How figures are shown on the page. Plain strings, so the template never formats a number.
# ---------------------------------------------------------------------------

CHART_W, CHART_H = 1200, 240
_LEFT, _RIGHT, _TOP, _BOTTOM = 56, 8, 10, 28


def compact(n: int) -> str:
    """12,345 -> 12.3k, 4,500,000 -> 4.5M. Whole numbers below a thousand."""
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def money_usd(value) -> str:
    value = Decimal(value)
    return f"${value:,.2f}" if value >= 1 or value == 0 else f"${value:.4f}"


def money_inr(value) -> str:
    return f"\u20b9{Decimal(value):,.2f}"


def labels(t: dict) -> dict:
    """The display strings for one block of totals."""
    return {
        "usd": money_usd(t["cost_usd"]),
        "inr": money_inr(t["cost_inr"]),
        "calls": f"{t['calls']:,}",
        "input": compact(t["input_tokens"]),
        "cached": compact(t["cached_tokens"]),
        "output": compact(t["output_tokens"]),
        "rows": f"{t['rows']:,}",
        "pages": f"{t['pages']:,}",
        "hit": f"{t['cache_hit_percent']}%" if t["cache_hit_percent"] is not None else "\u2014",
        "errors": f"{t['error_percent']}%" if t["error_percent"] is not None else "\u2014",
        "latency": f"{t['avg_latency_ms'] / 1000:.1f} s" if t["avg_latency_ms"] else "\u2014",
        "per_row": money_usd(t["usd_per_row"]) if t["usd_per_row"] is not None else "\u2014",
    }


def build_chart(daily: list[dict]) -> dict:
    """Bar geometry for the 30-day chart, as strings an SVG attribute can take. ``empty`` when nothing was spent."""
    peak = max((d["cost_micro"] for d in daily), default=0)
    if peak == 0:
        return {"empty": True, "width": CHART_W, "height": CHART_H}
    plot_w = CHART_W - _LEFT - _RIGHT
    plot_h = CHART_H - _TOP - _BOTTOM
    slot = plot_w / len(daily)
    bar = max(slot * 0.68, 4)
    base = _TOP + plot_h
    bars, ticks = [], []
    for i, d in enumerate(daily):
        x = _LEFT + i * slot + (slot - bar) / 2
        h = 0 if d["cost_micro"] == 0 else max(plot_h * d["cost_micro"] / peak, 2)
        bars.append(
            {
                "x": f"{x:.1f}",
                "y": f"{base - h:.1f}",
                "w": f"{bar:.1f}",
                "h": f"{h:.1f}",
                "title": f"{d['date']:%d-%m-%Y}: {money_usd(d['cost_usd'])}, {d['calls']} call(s)",
                "is_last": i == len(daily) - 1,
                "has_spend": d["cost_micro"] > 0,
            }
        )
        if i % 5 == 0 or i == len(daily) - 1:
            ticks.append({"x": f"{x + bar / 2:.1f}", "label": f"{d['date']:%d %b}"})
    grid = [
        {"y": f"{base - plot_h * f:.1f}", "label": money_usd(usd(int(peak * f))) if f else "$0"}
        for f in (0, 0.5, 1)
    ]
    return {
        "empty": False,
        "width": CHART_W,
        "height": CHART_H,
        "bars": bars,
        "ticks": ticks,
        "grid": grid,
        "base": f"{base:.1f}",
        "left": _LEFT,
        "right": CHART_W - _RIGHT,
        "label_y": f"{base + 18:.1f}",
    }


def _count(v: float) -> str:
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def _day_label(d: datetime.date) -> str:
    return f"{d:%d %b}"


def build_visuals(days, rows, events, window_start, now) -> dict:
    """The charts beside the spend chart: calls, cache, answer time, where tokens go, models, purposes and busy hours."""
    labels = [_day_label(d) for d in days]

    def get(d, key):
        return rows[d][key] if d in rows else 0

    answered = [int(get(d, "answered")) for d in days]
    limited = [int(get(d, "limited")) for d in days]
    failed = [int(get(d, "failed")) for d in days]
    calls_titles = [
        f"{_day_label(d)}: {a} answered, {r} rate limited, {f} failed"
        for d, a, r, f in zip(days, answered, limited, failed, strict=True)
    ]
    hit, hit_titles, latency, latency_titles = [], [], [], []
    for d in days:
        inp, cached = int(get(d, "input_tokens") or 0), int(get(d, "cached_tokens") or 0)
        hit.append(round(cached * 100 / inp) if inp else None)
        hit_titles.append(
            f"{_day_label(d)}: {round(cached * 100 / inp)}% from cache"
            if inp
            else f"{_day_label(d)}: no input"
        )
        ms = get(d, "latency")
        latency.append(float(ms) / 1000 if ms else None)
        latency_titles.append(
            f"{_day_label(d)}: {float(ms) / 1000:.1f} s average"
            if ms
            else f"{_day_label(d)}: no answered calls"
        )

    window = events.filter(at__gte=window_start)
    totals = window.aggregate(i=Sum("input_tokens"), c=Sum("cached_tokens"), o=Sum("output_tokens"))
    inp, cached, out = int(totals["i"] or 0), int(totals["c"] or 0), int(totals["o"] or 0)
    tokens = charts.donut(
        [
            ("Input, full price", max(inp - cached, 0), compact(max(inp - cached, 0))),
            ("Input, from cache", cached, compact(cached)),
            ("Output", out, compact(out)),
        ]
    )

    by_model = list(
        window.values("model")
        .annotate(cost=Sum("cost_micro_usd"), calls=Count("id"))
        .order_by("-cost", "-calls")[:6]
    )
    models = charts.donut(
        [
            (
                m["model"] or "Unknown",
                int(m["cost"] or 0) or int(m["calls"]),
                money_usd(usd(int(m["cost"] or 0))),
            )
            for m in by_model
        ]
    )

    by_purpose = list(
        window.values("purpose")
        .annotate(cost=Sum("cost_micro_usd"), calls=Count("id"))
        .order_by("-cost", "-calls")
    )
    purposes = charts.donut(
        [
            (
                Purpose(p["purpose"]).label if p["purpose"] in Purpose.values else p["purpose"],
                int(p["cost"] or 0) or int(p["calls"]),
                money_usd(usd(int(p["cost"] or 0))),
            )
            for p in by_purpose
        ]
    )

    hours = [0] * 24
    for r in window.annotate(h=ExtractHour("at")).values("h").annotate(c=Count("id")):
        hours[int(r["h"])] = int(r["c"])
    hour_labels = [f"{h:02d}:00" for h in range(24)]

    return {
        "calls": charts.stacked(
            [
                ("usage-seg-ok", answered),
                ("usage-seg-limited", limited),
                ("usage-seg-failed", failed),
            ],
            labels,
            calls_titles,
            width=600,
            height=220,
            fmt=_count,
        ),
        "cache": charts.line(
            hit, labels, hit_titles, width=600, height=220, fmt=lambda v: f"{v:.0f}%", top=100
        ),
        "latency": charts.line(
            latency, labels, latency_titles, width=600, height=220, fmt=lambda v: f"{v:.1f} s"
        ),
        "hours": charts.bars(
            hours,
            hour_labels,
            [f"{h:02d}:00 to {h:02d}:59: {c} call(s)" for h, c in enumerate(hours)],
            width=600,
            height=220,
            fmt=_count,
            every=3,
        ),
        "tokens": tokens,
        "models": models,
        "purposes": purposes,
    }


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
        .annotate(
            calls=Count("id"),
            cost=Sum("cost_micro_usd"),
            answered=Count("id", filter=Q(outcome=Outcome.OK)),
            limited=Count("id", filter=Q(outcome=Outcome.RATE_LIMITED)),
            failed=Count("id", filter=Q(outcome=Outcome.ERROR)),
            input_tokens=Sum("input_tokens"),
            cached_tokens=Sum("cached_tokens"),
            latency=Avg("latency_ms", filter=Q(outcome=Outcome.OK)),
        )
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

    visuals = build_visuals(days, daily_rows, events, window_start, now)

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
    today_totals = _totals(events.filter(at__gte=today_start))
    month_cost = month_totals["cost_micro"] or 0
    for block in purposes:
        block["share"] = round(block["cost_micro"] * 100 / month_cost) if month_cost else 0
        block["l"] = labels(block)
    for f in firms:
        f["share"] = round(int(f["cost_usd"] * 1_000_000) * 100 / month_cost) if month_cost else 0
    month_totals["l"] = labels(month_totals)
    today_totals["l"] = labels(today_totals)
    budget = Decimal(str(getattr(settings, "LLM_MONTHLY_BUDGET_USD", 0) or 0))
    return {
        "as_of": now,
        "today": today_totals,
        "month": month_totals,
        "chart": build_chart(daily),
        "visuals": visuals,
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
