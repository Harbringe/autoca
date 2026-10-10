"""Stock by item and month from invoice lines. Pure arithmetic: no database."""

import datetime
from decimal import Decimal

from ledger import inventory as inv

D = datetime.date


def m(date, direction, name, qty, rupees, unit="BAG"):
    return inv.Movement(date, direction, name, unit, Decimal(str(qty)), int(round(rupees * 100)))


def test_quantities_are_read_from_what_was_printed():
    assert inv.parse_quantity("60") == 60
    assert inv.parse_quantity("6.0 MT") == Decimal("6.0")
    assert inv.parse_quantity("2,000 kg") == 2000
    assert inv.parse_quantity("") is None and inv.parse_quantity("many") is None and inv.parse_quantity("0") is None


def test_months_run_april_to_march():
    months = inv.fy_months(2025)
    assert months[0] == "2025-04" and months[8] == "2025-12" and months[-1] == "2026-03" and len(months) == 12


def test_a_month_shows_what_came_in_what_went_out_and_what_is_left():
    rows = inv.summarise(
        [
            m(D(2025, 4, 5), "IN", "Cement PPC", 100, 30_000),
            m(D(2025, 4, 20), "OUT", "Cement PPC", 40, 14_000),
            m(D(2025, 5, 3), "IN", "Cement PPC", 50, 16_500),
        ],
        2025,
    )
    (item,) = rows
    april, may = item.months[0], item.months[1]
    assert (april.in_qty, april.out_qty, april.closing_qty) == (100, 40, 60)
    assert april.in_value_paise == 30_000_00 and april.out_value_paise == 14_000_00
    # 60 bags left at the average cost of 300 each
    assert april.closing_value_paise == 18_000_00
    assert (may.in_qty, may.closing_qty) == (50, 110)
    assert may.closing_value_paise == 18_000_00 + 16_500_00


def test_a_month_with_no_movement_carries_the_closing_balance_forward():
    (item,) = inv.summarise([m(D(2025, 4, 5), "IN", "Rice", 10, 1_000)], 2025)
    assert item.months[5].closing_qty == 10 and item.months[11].closing_value_paise == 1_000_00


def test_earlier_years_make_the_opening():
    (item,) = inv.summarise(
        [m(D(2024, 12, 1), "IN", "Rice", 100, 5_000), m(D(2025, 6, 1), "OUT", "Rice", 30, 2_400)], 2025
    )
    assert item.opening_qty == 100 and item.opening_value_paise == 5_000_00
    assert item.closing_qty == 70 and item.closing_value_paise == 3_500_00


def test_a_sale_before_any_purchase_shows_a_negative_quantity_not_a_hidden_one():
    (item,) = inv.summarise([m(D(2025, 4, 2), "OUT", "Oil", 5, 900)], 2025)
    assert item.months[0].closing_qty == -5


def test_two_spellings_of_one_product_are_one_item():
    rows = inv.summarise(
        [
            m(D(2025, 4, 5), "IN", "Ultratech Super PPC Cement", 60, 18_000),
            m(D(2025, 4, 9), "OUT", "ULTRATECH SUPER PPC CEMENT", 10, 3_400),
        ],
        2025,
    )
    assert len(rows) == 1 and rows[0].closing_qty == 50


def test_movements_after_the_year_are_left_out():
    rows = inv.summarise([m(D(2026, 4, 1), "IN", "Rice", 10, 1_000)], 2025)
    assert rows == []
