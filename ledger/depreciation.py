"""Depreciation of one asset, year by year. Pure arithmetic: no database, no money in floats.

Three ways to charge it, because the books and the tax return disagree and a CA keeps both:

* ``SLM``: straight line over a useful life, on cost less residual value (Companies Act, Schedule II). In the year of
  purchase, and the year of sale, it runs for the days the asset was in use.
* ``WDV``: a rate on the written-down value, also for the days in use (Companies Act, reducing balance).
* ``WDV_IT``: a rate on the written-down value under the Income-tax rule: the full rate if the asset was in use for 180
  days or more of the year, half the rate if fewer.

Financial years run April to March. Every figure is whole paise, rounded half up, and depreciation never takes the book
value below the residual value (zero for the income-tax method).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

SLM = "SLM"
WDV = "WDV"
WDV_IT = "WDV_IT"
METHODS = (SLM, WDV, WDV_IT)


@dataclass(frozen=True)
class AssetTerms:
    cost_paise: int
    put_to_use: datetime.date
    method: str
    #: SLM only: years of useful life.
    life_years: int = 0
    #: WDV and WDV_IT: the annual rate in basis points (1500 is 15%).
    rate_bp: int = 0
    #: What the asset is worth at the end of its life. Not depreciated below this.
    residual_paise: int = 0
    disposed_on: datetime.date | None = None


@dataclass(frozen=True)
class YearRow:
    financial_year: int
    opening_paise: int
    depreciation_paise: int
    closing_paise: int
    days_in_use: int
    #: Total depreciation charged up to and including this year.
    accumulated_paise: int


def fy_bounds(year: int) -> tuple[datetime.date, datetime.date]:
    return datetime.date(year, 4, 1), datetime.date(year + 1, 3, 31)


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def days_in_use(terms: AssetTerms, year: int) -> int:
    """Days of the financial year the asset was in use, counting the first and the last day."""
    start, end = fy_bounds(year)
    first = max(start, terms.put_to_use)
    last = min(end, terms.disposed_on) if terms.disposed_on else end
    return max((last - first).days + 1, 0)


def validate(terms: AssetTerms) -> str | None:
    """A sentence saying what is wrong with these terms, or None."""
    if terms.cost_paise <= 0:
        return "The cost must be more than zero."
    if terms.method not in METHODS:
        return f"The method must be one of {', '.join(METHODS)}."
    if not 0 <= terms.residual_paise < terms.cost_paise:
        return "The residual value must be less than the cost."
    if terms.method == SLM and terms.life_years <= 0:
        return "Straight-line depreciation needs the useful life in years."
    if terms.method in (WDV, WDV_IT) and not 0 < terms.rate_bp <= 10000:
        return "A written-down-value method needs a rate between 0 and 100 per cent."
    if terms.disposed_on and terms.disposed_on < terms.put_to_use:
        return "The asset cannot be sold before it was put to use."
    return None


def depreciation_for_year(terms: AssetTerms, year: int, opening_paise: int) -> tuple[int, int]:
    """Depreciation for one financial year, and the days in use, given the value at the start of it."""
    start, end = fy_bounds(year)
    days = days_in_use(terms, year)
    if days == 0:
        return 0, 0
    year_days = (end - start).days + 1
    floor = 0 if terms.method == WDV_IT else terms.residual_paise
    room = max(opening_paise - floor, 0)
    if terms.method == SLM:
        full = Decimal(terms.cost_paise - terms.residual_paise) / Decimal(terms.life_years)
        charge = _round(full * Decimal(days) / Decimal(year_days))
    elif terms.method == WDV:
        charge = _round(Decimal(opening_paise) * Decimal(terms.rate_bp) / Decimal(10000) * Decimal(days) / Decimal(year_days))
    else:  # WDV_IT: half rate when used for fewer than 180 days
        rate = Decimal(terms.rate_bp) / Decimal(10000)
        if days < 180:
            rate = rate / 2
        charge = _round(Decimal(opening_paise) * rate)
    return min(charge, room), days


def schedule(terms: AssetTerms, *, through_year: int) -> list[YearRow]:
    """Every year from the one the asset was put to use through ``through_year`` (a starting year, 2025 for FY 2025-26)."""
    first_year = terms.put_to_use.year if terms.put_to_use.month >= 4 else terms.put_to_use.year - 1
    rows: list[YearRow] = []
    value, accumulated = terms.cost_paise, 0
    for year in range(first_year, through_year + 1):
        charge, days = depreciation_for_year(terms, year, value)
        accumulated += charge
        rows.append(YearRow(year, value, charge, value - charge, days, accumulated))
        value -= charge
        if terms.disposed_on and fy_bounds(year)[1] >= terms.disposed_on:
            break
    return rows
