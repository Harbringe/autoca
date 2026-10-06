"""A payment to a supplier for something bought, with no invoice behind it, is listed until someone says why."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party
from classify.engine import review_queue

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def pay(api, client_record, ledger_name, group):
    """Place the statement's first payment on a ledger, to a supplier with no bills, and post it."""
    row = review_queue(client_record).filter(transaction__narration__icontains="AXOMB10000000001").first()
    supplier = make_party(api, client_record)
    ledger = make_ledger(api, client_record, ledger_name, group)
    placed = api.post(
        f"{V1}/classifications/{row.pk}/review/", {"ledger": ledger["id"], "party": supplier["id"], "learn": False}, format="json"
    )
    assert placed.status_code == 200, placed.content
    posted = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")
    assert posted.status_code == 201, posted.content
    return posted.json()[0]["id"]


def listed(api, client_record):
    items = api.get(f"{base(client_record)}/open-items/", {"kind": "payment_without_invoice"}).json()["items"]
    return items


def test_a_payment_for_goods_to_a_supplier_with_no_bills_is_listed(api, client_record, statement):
    entry = pay(api, client_record, "Purchases", "PURCHASE")

    items = listed(api, client_record)

    assert len(items) == 1 and items[0]["link"] == {"type": "entry", "id": entry}
    assert "has no invoice on file" in items[0]["summary"]


def test_saying_no_invoice_is_expected_clears_it(api, client_record, statement):
    entry = pay(api, client_record, "Purchases", "PURCHASE")

    done = api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "NO_INVOICE_EXPECTED"}, format="json")

    assert done.status_code == 200
    assert listed(api, client_record) == []


def test_waiting_for_an_invoice_moves_it_to_its_own_kind(api, client_record, statement):
    entry = pay(api, client_record, "Purchases", "PURCHASE")

    api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "NEEDS_INVOICE"}, format="json")

    assert listed(api, client_record) == []
    waiting = api.get(f"{base(client_record)}/open-items/", {"kind": "payment_needs_invoice"}).json()["items"]
    assert len(waiting) == 1


def test_a_large_ordinary_expense_is_listed_and_a_small_one_is_not(api, client_record, statement, monkeypatch):
    entry = pay(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")  # the statement's payment is Rs 15,00,000

    assert [i["link"]["id"] for i in listed(api, client_record)] == [entry]

    monkeypatch.setattr("ledger.openitems.LARGE_EXPENSE_PAISE", 10**12)
    assert listed(api, client_record) == []
