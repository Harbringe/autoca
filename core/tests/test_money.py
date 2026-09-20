"""Money is a whole number of paise, and the edges where that is enforced."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.money import MoneyError, format_inr, to_paise, to_rupees


@pytest.mark.parametrize(
    ("value", "paise"),
    [
        (Decimal("250.00"), 250_00),
        (Decimal("0.01"), 1),
        (Decimal("-1234.50"), -1234_50),
        ("1,00,000.00", 1_00_000_00),  # lakh grouping
        ("4,941,572.00", 49_41_572_00),  # thousands grouping, same statement
        ("7403.75", 7403_75),
        ("1,234.00 Cr", 1234_00),
        ("1,234.00 Dr", -1234_00),
        (250, 250_00),
    ],
)
def test_to_paise(value, paise):
    assert to_paise(value) == paise


def test_a_float_is_refused_outright():
    """By the time a float arrives the error is already baked in.

    Accepting it would make this function the place the corruption becomes
    permanent, rather than the place it was caught.
    """
    with pytest.raises(MoneyError, match="Refusing to convert the float"):
        to_paise(250.10)


def test_an_amount_finer_than_a_paisa_is_refused():
    """Rounding is a decision, not a side effect of storing a number."""
    with pytest.raises(MoneyError, match="finer than a paisa"):
        to_paise(Decimal("1.005"))


def test_a_narration_is_not_an_amount():
    with pytest.raises(MoneyError, match="Not a money value"):
        to_paise("Sweep/VO000000012345678")


def test_rupees_round_trip_exactly():
    for paise in (1, 250_00, 6_03_490_57, -49_41_572_00):
        assert to_paise(to_rupees(paise)) == paise


def test_the_float_that_started_all_this():
    """0.1 + 0.2 in paise. The reason the unit is an integer at all."""
    assert to_paise(Decimal("0.10")) + to_paise(Decimal("0.20")) == to_paise(Decimal("0.30"))


@pytest.mark.parametrize(
    ("paise", "text"),
    [
        (6_03_490_57, "₹6,03,490.57"),
        (1_24_189_43, "₹1,24,189.43"),
        (49_41_572_00, "₹49,41,572.00"),
        (250_00, "₹250.00"),
        (5, "₹0.05"),
        (0, "₹0.00"),
        (-1234_50, "-₹1,234.50"),
        (12_34_56_789_00, "₹12,34,56,789.00"),  # a crore
    ],
)
def test_indian_digit_grouping(paise, text):
    """Lakh and crore grouping, not thousands.

    ₹603,490.57 is instantly wrong to an Indian accountant and reads as software
    written for somewhere else.
    """
    assert format_inr(paise) == text
