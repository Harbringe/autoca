"""The open-items list: one place for everything that does not yet tie out.

Items are computed from the books, so each test changes the books and checks the item appears and then goes away.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from classify.models import LedgerGroup
from documents.models import Document, DocumentKind
from ledger import billing, openitems
from ledger.models import (
    AllocationKind,
    Direction,
    JournalEntry,
    JournalLine,
    LedgerOpening,
    VoucherType,
)
from ledger.tests.test_approval import client, firm, ledger, membership_for, senior  # noqa: F401
from ledger.tests.test_billing import (  # noqa: F401  (fixtures and helpers)
    books,
    make_party,
    payment_line,
    purchase,
)

pytestmark = pytest.mark.django_db


def kinds_of(client):
    return sorted(item.kind for item in openitems.open_items(client))


def test_clean_books_have_nothing_open(books):
    assert openitems.open_items(books) == []


def test_every_registered_kind_has_a_title():
    titles = openitems.kinds()

    assert {"bill_without_document", "payment_unallocated", "money_on_account", "party_out_of_balance"} <= set(titles)
    assert all(title for title in titles.values())


def test_a_bill_with_no_invoice_file_is_reported_until_one_is_attached(books, senior):
    purchase(books, senior)
    assert kinds_of(books) == ["bill_without_document"]
    item = openitems.open_items(books)[0]
    assert item.amount_paise == 11_800_000 and item.link["type"] == "bill" and "Ravi Traders" in item.summary

    # A bill booked with its file is not an open item.
    document = Document.objects.create(
        firm_id=books.firm_id, client=books, kind=DocumentKind.PURCHASE_INVOICE, sha256="f" * 64
    )
    purchase(books, senior, make_party(books, "Shah Stationers", gstin="24AAACS1234A1Z9"), document=document)
    assert len(openitems.open_items(books, only=["bill_without_document"])) == 1


def test_a_payment_not_allocated_to_a_bill_is_reported_then_clears_when_allocated(books, senior):
    bill = purchase(books, senior, document=Document.objects.create(
        firm_id=books.firm_id, client=books, kind=DocumentKind.PURCHASE_INVOICE, sha256="a" * 64
    ))
    line = payment_line(books, bill.party, 11_800_000)

    before = openitems.open_items(books, only=["payment_unallocated"])
    billing.allocate(line, bill=bill, amount_paise=11_800_000)
    after = openitems.open_items(books, only=["payment_unallocated"])

    assert [item.amount_paise for item in before] == [11_800_000]
    assert before[0].since == datetime.date(2025, 10, 20)
    assert after == []


def test_a_part_allocated_payment_reports_only_what_is_left(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 5_000_000)
    billing.allocate(line, bill=bill, amount_paise=3_000_000)

    items = openitems.open_items(books, only=["payment_unallocated"])

    assert [item.amount_paise for item in items] == [2_000_000]


def test_an_advance_is_reported_until_it_is_applied(books, senior):
    party = make_party(books)
    bill = purchase(books, senior, party)
    advance = payment_line(books, party, 2_000_000)
    held = billing.allocate(advance, amount_paise=2_000_000, kind=AllocationKind.ADVANCE)

    assert [i.amount_paise for i in openitems.open_items(books, only=["money_on_account"])] == [2_000_000]
    assert openitems.total_held(books) == 2_000_000

    billing.apply_unapplied(held, bill, amount_paise=2_000_000)

    assert openitems.open_items(books, only=["money_on_account"]) == []
    assert openitems.total_held(books) == 0


def test_a_party_whose_ledger_and_bills_disagree_is_reported(books, senior):
    bill = purchase(books, senior)
    bill.party.refresh_from_db()
    LedgerOpening.objects.create(
        firm_id=books.firm_id, client=books, ledger=bill.party.ledger, financial_year=2025, signed_paise=-500_000
    )

    items = openitems.open_items(books, only=["party_out_of_balance"])

    assert [(i.kind, i.amount_paise) for i in items] == [("party_out_of_balance", 500_000)]
    assert items[0].link == {"type": "party", "id": str(bill.party.pk)}


def test_items_come_oldest_first(books, senior):
    party = make_party(books)
    purchase(books, senior, party, reference="OLD", bill_date=datetime.date(2025, 6, 1))
    purchase(books, senior, party, reference="NEW", bill_date=datetime.date(2025, 9, 1))

    dates = [item.since for item in openitems.open_items(books, only=["bill_without_document"])]

    assert dates == sorted(dates) and dates[0] == datetime.date(2025, 6, 1)


def test_another_clients_items_are_not_mixed_in(books, senior, firm):
    from core.models import Client

    other = Client.objects.create(firm=firm, name="Someone Else", fy_start=datetime.date(2025, 4, 1))
    purchase(books, senior)

    assert openitems.open_items(other) == []


def test_a_new_document_type_adds_a_detector_not_a_report(books, monkeypatch):
    """The extension point: a later stage registers what can be left unmatched about its documents."""
    monkeypatch.setattr(openitems, "_DETECTORS", dict(openitems._DETECTORS))

    @openitems.detector("asset_without_invoice", "A fixed asset with no purchase invoice")
    def assets(client):
        yield openitems.OpenItem(kind="asset_without_invoice", client_id=client.pk, summary="Lathe machine has no invoice.")

    assert "asset_without_invoice" in openitems.kinds()
    assert [i.kind for i in openitems.open_items(books)] == ["asset_without_invoice"]
    with pytest.raises(ValueError, match="already registered"):
        openitems.detector("asset_without_invoice", "again")(assets)


def test_a_party_tag_on_an_expense_line_is_not_money_on_the_partys_account(books, senior):
    """The older bank flow tags the party on the expense line of a payment booked straight to an expense head.
    That is not money moved on the party's own account, so it must not appear as an unallocated payment."""
    party = make_party(books)
    purchase(books, senior, party)  # gives the party its own ledger
    entry = JournalEntry.objects.create(
        firm_id=books.firm_id, client=books, entry_no=1, financial_year=2025, entry_date=datetime.date(2025, 10, 20),
        voucher_type=VoucherType.PAYMENT, narration="Paid the old way", approved_at=timezone.now(),
    )
    expense = ledger(books, "Office Expenses")
    bank_ledger = ledger(books, "Axis Bank A/c 9999", LedgerGroup.BANK)
    JournalLine.objects.bulk_create([
        JournalLine.build(entry=entry, ledger_account=expense, party=party, direction=Direction.DEBIT, amount_paise=10_000),
        JournalLine.build(entry=entry, ledger_account=bank_ledger, direction=Direction.CREDIT, amount_paise=10_000),
    ])

    assert openitems.open_items(books, only=["payment_unallocated"]) == []
