"""The text of an uploaded invoice is untrusted: a line is cut to a sane length and no pattern is slow on a long run of digits."""

from __future__ import annotations

import time

from ledger import invoice_reader
from ledger.invoice_reader import _LABELS, _RATE, MAX_LINE_LENGTH, _amounts_on


def test_a_huge_digit_run_on_a_labelled_line_is_read_in_a_moment():
    lines = ["Total " + "1" * 130_000, "CGST " + "9" * 130_000]
    started = time.perf_counter()
    for name, label in _LABELS.items():
        _amounts_on(lines, label, name)
    assert time.perf_counter() - started < 2.0


def test_the_rate_pattern_is_linear_on_a_long_run_of_digits():
    started = time.perf_counter()
    assert _RATE.sub(" ", "1" * 130_000) == "1" * 130_000  # no percent sign: nothing removed
    assert time.perf_counter() - started < 1.0


def test_rates_are_still_dropped_and_amounts_still_read():
    assert _RATE.sub(" ", "CGST @ 9% 180.00").split() == ["CGST", "@", "180.00"]
    assert _RATE.sub(" ", "rate 2.5 % amount 45.00").split() == ["rate", "amount", "45.00"]
    assert _amounts_on(["CGST @ 9% 180.00"], _LABELS["cgst"], "cgst") == [18000]


def test_a_line_is_cut_before_anything_looks_at_it():
    assert MAX_LINE_LENGTH == 300
    assert hasattr(invoice_reader, "_RATE")
