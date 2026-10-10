"""A bill inside signed-off books is put right by a dated journal, never by editing it."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_bills import (  # noqa: F401  (fixtures and helpers)
    V1,
    base,
    make_ledger,
    post_bill,
    ravi,
    voucher,
)
from classify.models import LedgerAccount
from core.db.session import firm_context
from ledger.models import ChangeAction, EntryChange, JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def purchases(api, client_record):
    return make_ledger(api, client_record, "Purchases", "PURCHASE")


@pytest.fixture
def repairs(api, client_record):
    return make_ledger(api, client_record, "Repairs", "INDIRECT_EXPENSE")


def sealed_bill(api, client_record, ravi, purchases):
    bill = post_bill(api, client_record, voucher(ravi, purchases, bill_date="2025-05-10")).json()
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2026, 3, 31))
    return bill


def rectify(api, bill, source, target, **over):
    body = {
        "from_ledger": source["id"], "to_ledger": target["id"], "amount_paise": 1_00_000,
        "reason": "Booked to purchases, was a repair", "date": "2026-04-05", **over,
    }
    return api.post(f"{V1}/journal-entries/{bill['entry']}/rectify/", body, format="json")


def test_a_journal_moves_the_amount_and_the_original_stays_as_it_was(api, client_record, ravi, purchases, repairs):
    bill = sealed_bill(api, client_record, ravi, purchases)

    response = rectify(api, bill, purchases, repairs)

    assert response.status_code == 201, response.content
    with firm_context(client_record.firm_id):
        journal = JournalEntry.objects.get(pk=response.json()["id"])
        moved = sorted((line.ledger_account.name, line.direction, line.amount_paise) for line in journal.lines.all())
        assert moved == [("Purchases", "CR", 1_00_000), ("Repairs", "DR", 1_00_000)]
        assert journal.entry_date == datetime.date(2026, 4, 5) and "Booked to purchases" in journal.narration
        assert EntryChange.objects.filter(entry_id=bill["entry"], action=ChangeAction.RECTIFIED).count() == 1


def test_a_date_inside_the_sealed_books_is_refused(api, client_record, ravi, purchases, repairs):
    bill = sealed_bill(api, client_record, ravi, purchases)

    refused = rectify(api, bill, purchases, repairs, date="2026-03-31")

    assert refused.status_code == 422 and "sealed" in refused.json()["detail"]


def test_an_entry_in_open_books_is_not_rectified_this_way(api, client_record, ravi, purchases, repairs):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()

    refused = rectify(api, bill, purchases, repairs)

    assert refused.status_code == 422 and "not inside signed-off books" in refused.json()["detail"]


def test_more_than_the_entry_put_there_is_refused_even_over_two_goes(api, client_record, ravi, purchases, repairs):
    bill = sealed_bill(api, client_record, ravi, purchases)
    total = next(line["amount_paise"] for line in api.get(f"{V1}/journal-entries/{bill['entry']}/").json()["lines"] if line["ledger_name"] == "Purchases")

    assert rectify(api, bill, purchases, repairs, amount_paise=total).status_code == 201
    again = rectify(api, bill, purchases, repairs, amount_paise=1)

    assert again.status_code == 422 and "more than" in again.json()["detail"]


def test_a_party_account_and_a_reason_less_request_are_refused(api, client_record, ravi, purchases, repairs):
    bill = sealed_bill(api, client_record, ravi, purchases)

    no_reason = rectify(api, bill, purchases, repairs, reason="x")
    with firm_context(client_record.firm_id):
        party_ledger = LedgerAccount.objects.get(client=client_record, party_record__pk=ravi["id"])
    party = rectify(api, bill, purchases, {"id": str(party_ledger.pk)})

    assert no_reason.status_code == 422 and "why" in no_reason.json()["detail"]
    assert party.status_code == 422


def test_the_tds_return_pack_is_empty_without_deductions_and_wants_its_parameters(api, client_record):
    url = f"{base(client_record)}/tds/return/"

    empty = api.get(url, {"fy": 2025, "quarter": 1})
    export = api.get(f"{url}export/", {"fy": 2025, "quarter": 1})
    missing = api.get(url)

    assert empty.status_code == 200 and empty.json()["deductees"] == [] and empty.json()["due"] == "2025-07-31"
    assert export.status_code == 200 and export.content[:2] == b"PK"
    assert missing.status_code == 400


def test_opening_stock_and_a_count_adjustment_show_in_the_inventory_report(api, client_record):
    stock_url = f"{base(client_record)}/stock-entries/"
    opening = api.post(stock_url, {"kind": "OPENING", "entry_date": "2025-04-01", "name": "Widget", "unit": "pcs", "quantity": "100", "value_paise": 50_000_00}, format="json")
    loss = api.post(stock_url, {"kind": "ADJUSTMENT", "entry_date": "2025-06-30", "direction": "OUT", "name": "Widget", "unit": "pcs", "quantity": "4", "value_paise": 0, "note": "Damaged"}, format="json")

    report = api.get(f"{base(client_record)}/inventory/", {"fy": 2025}).json()
    refused = api.post(stock_url, {"kind": "OPENING", "entry_date": "2025-04-01", "name": "Widget", "quantity": "0"}, format="json")

    assert opening.status_code == 201 and loss.status_code == 201, (opening.content, loss.content)
    (item,) = report["items"]
    assert item["name"] == "Widget" and str(item["closing_qty"]).startswith("96")
    assert refused.status_code == 400
