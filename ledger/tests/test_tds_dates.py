"""TDS due dates and quarters: pure."""

from __future__ import annotations

import datetime

from ledger.tds import due_date, quarter_of


def test_tds_is_due_on_the_seventh_of_the_next_month():
    assert due_date(2025, 5) == datetime.date(2025, 6, 7)
    assert due_date(2025, 12) == datetime.date(2026, 1, 7)


def test_march_is_due_on_30_april():
    assert due_date(2026, 3) == datetime.date(2026, 4, 30)


def test_quarters_run_april_to_march():
    assert [quarter_of(m) for m in (4, 6, 7, 9, 10, 12, 1, 3)] == [1, 1, 2, 2, 3, 3, 4, 4]
