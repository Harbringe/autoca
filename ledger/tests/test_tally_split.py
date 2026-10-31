"""Splitting a large vouchers export into one import per calendar month. Pure: no database."""

from __future__ import annotations

import datetime

from ledger.tally_split import split_by_month
from ledger.tally_vouchers import ParsedVoucher, VoucherLine


def v(guid: str, date: datetime.date) -> ParsedVoucher:
    return ParsedVoucher(
        ordinal=1, guid=guid, tally_type="Journal", number=guid, date=date, party="", narration="", reference="",
        party_gstin="", own_gstin="", lines=(VoucherLine("A", 100, False), VoucherLine("B", -100, False)),
    )


def test_vouchers_are_grouped_by_month_in_date_order():
    out = split_by_month([v("c", datetime.date(2025, 5, 2)), v("a", datetime.date(2025, 4, 9)), v("b", datetime.date(2025, 4, 1))])
    assert [m for m, _ in out] == ["2025-04", "2025-05"]
    assert [x.guid for x in out[0][1]] == ["a", "b"], "the file's own order is kept inside a month"


def test_a_year_boundary_gives_separate_months():
    out = split_by_month([v("x", datetime.date(2025, 3, 31)), v("y", datetime.date(2025, 4, 1))])
    assert [m for m, _ in out] == ["2025-03", "2025-04"]


def test_every_voucher_lands_in_exactly_one_month():
    items = [v(str(i), datetime.date(2025, 1 + i % 12, 1 + i % 27)) for i in range(60)]
    out = split_by_month(items)
    assert sorted(x.guid for _, group in out for x in group) == sorted(x.guid for x in items)


def test_no_vouchers_gives_no_months():
    assert split_by_month([]) == []
