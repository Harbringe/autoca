"""Each voucher series counts on its own, and its numbers can be shown with a prefix and padding."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from core.db.session import firm_context
from ledger.approval import allocate_voucher_number
from ledger.books import _renumber
from ledger.models import JournalEntry, NumberingFormat, VoucherType
from ledger.numbering import format_voucher_number
from ledger.tests.test_tally_voucher_import import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    member,
    senior,
)

pytestmark = pytest.mark.django_db


def entry(firm, client, *, type_name: str, number: int, day: int = 1) -> JournalEntry:
    return JournalEntry.objects.create(
        firm_id=firm.pk, client=client, entry_no=number, financial_year=2025, entry_date=datetime.date(2025, 4, day),
        voucher_type=VoucherType.SALES, type_name=type_name, approved_at=timezone.now(),
    )


def test_each_series_counts_on_its_own(firm, client):
    with firm_context(firm.pk):
        assert [allocate_voucher_number(client, 2025, "Sales") for _ in range(2)] == [1, 2]
        assert allocate_voucher_number(client, 2025, "Sales", "GST SALE") == 1
        assert allocate_voucher_number(client, 2025, "Sales") == 3


def test_the_format_prefixes_and_pads(firm, client):
    with firm_context(firm.pk):
        NumberingFormat.objects.create(firm_id=firm.pk, client=client, voucher_type="Sales", type_name="", prefix="S/{fy}/", padding=4)
        assert format_voucher_number(client, "Sales", "", 7, 2025) == "S/25-26/0007"


def test_no_format_shows_the_plain_number(firm, client):
    with firm_context(firm.pk):
        assert format_voucher_number(client, "Sales", "", 7, 2025) == "7"


def test_a_series_without_its_own_format_does_not_borrow_another_series(firm, client):
    with firm_context(firm.pk):
        NumberingFormat.objects.create(firm_id=firm.pk, client=client, voucher_type="Sales", type_name="", prefix="S/", padding=3)
        assert format_voucher_number(client, "Sales", "GST SALE", 7, 2025) == "7"


def test_changing_the_format_changes_the_shown_number_not_the_stored_one(firm, client):
    with firm_context(firm.pk):
        row = entry(firm, client, type_name="", number=7)
        fmt = NumberingFormat.objects.create(firm_id=firm.pk, client=client, voucher_type="Sales", type_name="", prefix="A", padding=2)
        assert format_voucher_number(client, "Sales", "", row.entry_no, 2025) == "A07"
        NumberingFormat.objects.filter(pk=fmt.pk).update(prefix="B", padding=0)
        assert format_voucher_number(client, "Sales", "", row.entry_no, 2025) == "B7"
        row.refresh_from_db()
        assert row.entry_no == 7


def test_sign_off_renumbering_keeps_each_series_gapless_and_apart(firm, client):
    with firm_context(firm.pk):
        for name in ("", "GST SALE"):  # the counters exist, as they do once vouchers have been numbered
            allocate_voucher_number(client, 2025, "Sales", name)
        plain = [entry(firm, client, type_name="", number=n, day=d) for n, d in ((1, 1), (3, 2))]
        own = [entry(firm, client, type_name="GST SALE", number=n, day=d) for n, d in ((2, 3), (5, 4))]
        _renumber(client, None, after=None)
        assert [JournalEntry.objects.get(pk=e.pk).entry_no for e in plain] == [1, 2]
        assert [JournalEntry.objects.get(pk=e.pk).entry_no for e in own] == [1, 2]
        assert allocate_voucher_number(client, 2025, "Sales") == 3
        assert allocate_voucher_number(client, 2025, "Sales", "GST SALE") == 3
