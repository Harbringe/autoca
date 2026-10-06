"""Depreciation arithmetic: pure, so it is checked against figures worked by hand."""

from __future__ import annotations

import datetime

from ledger.depreciation import (
    SLM,
    WDV,
    WDV_IT,
    AssetTerms,
    days_in_use,
    depreciation_for_year,
    schedule,
    validate,
)

D = datetime.date


def terms(**over):
    base = {"cost_paise": 10_00_000_00, "put_to_use": D(2025, 4, 1), "method": SLM, "life_years": 10, "residual_paise": 0}
    return AssetTerms(**{**base, **over})


def test_straight_line_charges_cost_less_residual_over_the_life_in_a_full_year():
    t = terms(residual_paise=50_000_00)  # 5% residual on 10,00,000

    rows = schedule(t, through_year=2026)

    assert rows[0].depreciation_paise == 95_000_00  # (10,00,000 - 50,000) / 10
    assert rows[1].opening_paise == 9_05_000_00 and rows[1].closing_paise == 8_10_000_00


def test_the_first_year_runs_for_the_days_the_asset_was_in_use():
    t = terms(put_to_use=D(2025, 10, 1))  # 182 of 365 days

    charge, days = depreciation_for_year(t, 2025, t.cost_paise)

    assert days == 182
    assert charge == round(10_00_000_00 / 10 * 182 / 365)


def test_straight_line_stops_at_the_residual_value():
    t = terms(life_years=2, residual_paise=100_000_00)

    rows = schedule(t, through_year=2030)

    assert rows[-1].closing_paise == 100_000_00
    assert sum(r.depreciation_paise for r in rows) == 9_00_000_00


def test_written_down_value_takes_the_rate_on_what_is_left():
    t = terms(method=WDV, rate_bp=1500, life_years=0)

    rows = schedule(t, through_year=2026)

    assert rows[0].depreciation_paise == 1_50_000_00
    assert rows[1].depreciation_paise == 1_27_500_00  # 15% of 8,50,000


def test_the_income_tax_method_halves_the_rate_below_180_days():
    late = terms(method=WDV_IT, rate_bp=1500, life_years=0, put_to_use=D(2026, 1, 15))  # 76 days
    early = terms(method=WDV_IT, rate_bp=1500, life_years=0, put_to_use=D(2025, 6, 1))  # 304 days

    assert depreciation_for_year(late, 2025, late.cost_paise)[0] == 75_000_00
    assert depreciation_for_year(early, 2025, early.cost_paise)[0] == 1_50_000_00


def test_a_sold_asset_is_depreciated_to_the_day_of_sale_and_no_further():
    t = terms(put_to_use=D(2025, 4, 1), disposed_on=D(2025, 9, 30))  # 183 days

    rows = schedule(t, through_year=2030)

    assert len(rows) == 1 and rows[0].days_in_use == 183
    assert days_in_use(t, 2026) == 0


def test_the_year_of_purchase_before_april_belongs_to_the_earlier_year():
    rows = schedule(terms(put_to_use=D(2026, 2, 10)), through_year=2026)

    assert rows[0].financial_year == 2025 and rows[0].days_in_use == 50


def test_nothing_is_charged_for_a_year_before_the_asset_was_in_use():
    assert depreciation_for_year(terms(put_to_use=D(2026, 6, 1)), 2025, 10_00_000_00) == (0, 0)


def test_terms_that_cannot_work_say_why():
    assert "cost" in validate(terms(cost_paise=0))
    assert "life" in validate(terms(life_years=0))
    assert "rate" in validate(terms(method=WDV, rate_bp=0))
    assert "residual" in validate(terms(residual_paise=10_00_000_00))
    assert "sold before" in validate(terms(disposed_on=D(2025, 3, 1)))
    assert validate(terms()) is None
