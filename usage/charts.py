"""Chart geometry for the usage page, as plain numbers and strings an SVG attribute can take.

Nothing here touches the database or Django, so each chart is checked on its own. The template only places what these return.
Sizes are in SVG user units; the page scales the drawing to its card.
"""

from __future__ import annotations

import math

LEFT, RIGHT, TOP, BOTTOM = 56, 8, 10, 28


def nice_max(value: float) -> float:
    """The next round number at or above ``value``: 1, 2, 2.5, 5 or 10 times a power of ten. 1 for nothing."""
    if value <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * power:
            return step * power
    return 10 * power


def _f(x: float) -> str:
    return f"{x:.1f}"


def _frame(width: int, height: int) -> tuple[float, float, float]:
    plot_w = width - LEFT - RIGHT
    plot_h = height - TOP - BOTTOM
    return plot_w, plot_h, TOP + plot_h


def _grid(top: float, plot_h: float, base: float, fmt) -> list[dict]:
    return [{"y": _f(base - plot_h * f), "label": fmt(top * f)} for f in (0, 0.5, 1)]


def _ticks(labels: list[str], centres: list[float], every: int) -> list[dict]:
    last = len(labels) - 1
    return [
        {"x": _f(centres[i]), "label": labels[i]}
        for i in range(len(labels))
        if i % every == 0 or i == last
    ]


def bars(values, labels, titles, *, width=600, height=220, fmt=str, every=5, top=None) -> dict:
    """One bar per value. The last bar is flagged so it can be drawn as 'now'."""
    peak = max(values, default=0)
    if peak <= 0:
        return {"empty": True, "width": width, "height": height}
    top = top or nice_max(peak)
    plot_w, plot_h, base = _frame(width, height)
    slot = plot_w / len(values)
    bar = max(slot * 0.68, 4)
    out, centres = [], []
    for i, v in enumerate(values):
        x = LEFT + i * slot + (slot - bar) / 2
        h = 0 if v <= 0 else max(plot_h * v / top, 2)
        centres.append(x + bar / 2)
        out.append(
            {
                "x": _f(x),
                "y": _f(base - h),
                "w": _f(bar),
                "h": _f(h),
                "title": titles[i],
                "is_last": i == len(values) - 1,
                "has_value": v > 0,
            }
        )
    return {
        "empty": False,
        "width": width,
        "height": height,
        "bars": out,
        "ticks": _ticks(labels, centres, every),
        "grid": _grid(top, plot_h, base, fmt),
        "left": LEFT,
        "right": width - RIGHT,
        "label_y": _f(base + 18),
    }


def stacked(series, labels, titles, *, width=600, height=220, fmt=str, every=5) -> dict:
    """Bars split into segments. ``series`` is ``[(css class, values)]`` from the bottom up, all the same length."""
    n = len(labels)
    totals = [sum(values[i] for _, values in series) for i in range(n)]
    peak = max(totals, default=0)
    if peak <= 0:
        return {"empty": True, "width": width, "height": height}
    top = nice_max(peak)
    plot_w, plot_h, base = _frame(width, height)
    slot = plot_w / n
    bar = max(slot * 0.68, 4)
    out, centres = [], []
    for i in range(n):
        x = LEFT + i * slot + (slot - bar) / 2
        centres.append(x + bar / 2)
        y = base
        segments = []
        for cls, values in series:
            h = plot_h * values[i] / top
            if values[i] > 0:
                h = max(h, 2)
                y -= h
                segments.append({"y": _f(y), "h": _f(h), "cls": cls})
        out.append({"x": _f(x), "w": _f(bar), "segments": segments, "title": titles[i]})
    return {
        "empty": False,
        "width": width,
        "height": height,
        "bars": out,
        "ticks": _ticks(labels, centres, every),
        "grid": _grid(top, plot_h, base, fmt),
        "left": LEFT,
        "right": width - RIGHT,
        "label_y": _f(base + 18),
    }


def line(values, labels, titles, *, width=600, height=220, fmt=str, every=5, top=None) -> dict:
    """A line through the points that have a value; a day with none (``None``) breaks the line instead of dropping to zero."""
    known = [v for v in values if v is not None]
    if not known or max(known) <= 0:
        return {"empty": True, "width": width, "height": height}
    top = top or nice_max(max(known))
    plot_w, plot_h, base = _frame(width, height)
    slot = plot_w / len(values)
    runs, current, dots, centres = [], [], [], []
    for i, v in enumerate(values):
        cx = LEFT + i * slot + slot / 2
        centres.append(cx)
        if v is None:
            if current:
                runs.append(current)
            current = []
            continue
        cy = base - plot_h * min(v, top) / top
        current.append(f"{_f(cx)},{_f(cy)}")
        dots.append(
            {"cx": _f(cx), "cy": _f(cy), "title": titles[i], "is_last": i == len(values) - 1}
        )
    if current:
        runs.append(current)
    return {
        "empty": False,
        "width": width,
        "height": height,
        "runs": [" ".join(r) for r in runs if len(r) > 1],
        "dots": dots,
        "ticks": _ticks(labels, centres, every),
        "grid": _grid(top, plot_h, base, fmt),
        "left": LEFT,
        "right": width - RIGHT,
        "label_y": _f(base + 18),
    }


def donut(parts, *, size=180, radius=60) -> dict:
    """A ring split by value. ``parts`` is ``[(label, value, value label)]``; zero parts are left out. Slices are
    circle strokes cut with a dash pattern, so the page needs no path maths."""
    parts = [(label, value, shown) for label, value, shown in parts if value > 0]
    total = sum(value for _, value, _ in parts)
    if total <= 0:
        return {"empty": True, "size": size}
    circumference = 2 * math.pi * radius
    offset = 0.0
    out = []
    for i, (label, value, shown) in enumerate(parts):
        length = circumference * value / total
        out.append(
            {
                "label": label,
                "shown": shown,
                "percent": round(value * 100 / total),
                "cls": f"usage-c{i % 6}",
                "dash": f"{length:.2f}",
                "gap": f"{circumference - length:.2f}",
                "offset": f"{-offset:.2f}",
            }
        )
        offset += length
    centre = size / 2
    return {
        "empty": False,
        "size": size,
        "cx": _f(centre),
        "cy": _f(centre),
        "r": _f(radius),
        "stroke": 26,
        "slices": out,
    }
