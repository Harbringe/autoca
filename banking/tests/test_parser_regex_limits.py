"""Statement text is untrusted: a cell of a hundred thousand digits must not make a money pattern slow."""

from __future__ import annotations

import re
import time

from banking.parsers import bob, card

LONG_DIGITS = "7" * 130_000


def test_the_baroda_patterns_pass_over_a_huge_digit_run_in_a_moment():
    started = time.perf_counter()
    assert bob._BALANCE.findall(LONG_DIGITS) == []
    assert re.findall(bob._MONEY, LONG_DIGITS) == []
    assert bob._BALANCE.sub(" ", LONG_DIGITS) == LONG_DIGITS
    assert time.perf_counter() - started < 1.0


def test_the_card_money_token_passes_over_a_huge_digit_run_in_a_moment():
    started = time.perf_counter()
    assert card.MONEY_TOKEN.search(LONG_DIGITS) is None
    assert time.perf_counter() - started < 1.0


def test_ordinary_figures_are_still_read():
    assert bob._BALANCE.findall("NEFT 1,23,456.78 12,000.50 Cr") == [("12,000.50", "Cr")]
    assert re.findall(bob._MONEY, "paid 500.00 and 1,23,456.78") == ["500.00", "1,23,456.78"]
    assert card.MONEY_TOKEN.search("Purchase 1,234.56 Dr").group(0).strip().startswith("1,234.56")
    assert card.MONEY_TOKEN.search("Refund (250.00)").group(0).startswith("(250.00)")
    assert card.MONEY_TOKEN.search("Payment -750.00 Cr").group(0).startswith("-750.00")
