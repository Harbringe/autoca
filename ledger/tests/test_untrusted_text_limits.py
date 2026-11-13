"""Text read out of an uploaded file is bounded before a pattern runs on it."""

from __future__ import annotations

import time

import pytest

from core.masking import MAX_TEXT_LENGTH, mask, mask_text
from ledger.tally_vouchers import _quantity


@pytest.mark.parametrize(
    "text, expected",
    [
        ("600 BOX", ("600", "BOX")),
        ("1,200.500 Kgs = 1 Nos", ("1200.500", "Kgs")),
        ("  12.5 Ltr", ("12.5", "Ltr")),
        (".5 Kg", (".5", "Kg")),
        ("0 Nos", None),
        ("none", None),
        ("", None),
    ],
)
def test_quantities_are_read_as_before(text, expected):
    assert _quantity(text) == expected


def test_a_quantity_with_a_huge_digit_run_and_a_newline_is_read_in_a_moment():
    started = time.perf_counter()
    _quantity("1" * 3_000 + "\nx\ny")
    _quantity("1" * 130_000 + "\n" + "x" * 100)
    assert time.perf_counter() - started < 1.0


def test_a_huge_unbroken_narration_is_masked_in_a_moment():
    started = time.perf_counter()
    mask("A" * 130_000)
    mask(("a.b-c" * 40_000) + " no at sign")
    assert time.perf_counter() - started < 2.0


def test_masking_still_replaces_identifiers_and_cuts_only_the_excess():
    assert mask_text("pay to person@example.com now") == "pay to <EMAIL> now"
    assert len(mask("x" * (MAX_TEXT_LENGTH + 500)).text) == MAX_TEXT_LENGTH
