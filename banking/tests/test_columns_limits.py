"""A table's shape is chosen by whoever uploads it, so the layout search is bounded however wide it is."""

from __future__ import annotations

import time

import pytest

from banking.parsers import columns
from banking.parsers.columns import ColumnInferenceError, infer_columns


def wide_table(money_columns: int, rows: int = 150) -> list[list[str]]:
    """A date column and ``money_columns`` columns of distinct decimals, none of which follows any balance."""
    return [[f"{1 + i % 28:02d}-01-2025", *(f"{(i + 1) * 17 + c * 3 + 0.37:.2f}" for c in range(money_columns))] for i in range(rows)]


def test_a_headerless_table_with_dozens_of_money_columns_is_refused_quickly():
    started = time.perf_counter()
    with pytest.raises(ColumnInferenceError):
        infer_columns(None, wide_table(59))
    # About 195,000 layouts used to be tried; the search is now capped, so this ends in a moment.
    assert time.perf_counter() - started < 20.0  # generous: a busy CI runner took 5.1 s once; unbounded, it ran for minutes


def test_the_search_gives_up_after_a_fixed_number_of_layouts(monkeypatch):
    tried = []
    real = columns._reproduces_balances

    def counting(rows, mapping, liability=False):
        tried.append(1)
        return real(rows, mapping, liability)

    monkeypatch.setattr(columns, "_reproduces_balances", counting)
    with pytest.raises(ColumnInferenceError):
        infer_columns(None, wide_table(40))
    assert 0 < len(tried) <= columns.MAX_LAYOUTS_TRIED


def test_an_ordinary_statement_layout_is_still_found():
    rows, balance = [], 1000_00
    for i in range(30):
        debit = (i % 3 == 0) * (100 + i)
        credit = (i % 3 != 0) * (50 + i)
        balance += credit * 100 - debit * 100
        rows.append([f"{1 + i % 28:02d}-01-2025", f"{debit:.2f}" if debit else "", f"{credit:.2f}" if credit else "", f"{balance / 100:.2f}"])
    mapping = infer_columns(None, rows)
    assert mapping is not None
