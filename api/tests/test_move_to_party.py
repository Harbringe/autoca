"""A payment already posted to a head is moved onto its party's account and settled, in one step a person decides."""

from __future__ import annotations

import datetime

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base, make_ledger
from api.tests.test_settlement_api import supplier_bill_for, the_payment
from ledger.models import EntryChange, JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def posted_to_a_head(api, client_record, party):
    """The statement's payment, placed on an expense head with the party recorded, and posted."""
    row = the_payment(client_record)
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")
    placed = api.post(
        f"{V1}/classifications/{row.pk}/review/", {"ledger": expense["id"], "party": party["id"], "learn": False}, format="json"
    )
    assert placed.status_code == 200, placed.content
    posted = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")
    assert posted.status_code == 201, posted.content
    return posted.json()[0]["id"], row.transaction.amount_paise


def ledgers_of(entry_id):
    entry = JournalEntry.objects.get(pk=entry_id)
    return {line.ledger_account.name for line in entry.lines.select_related("ledger_account")}


def move_url(entry):
    return f"{V1}/journal-entries/{entry}/move-to-party/"


@pytest.fixture
def setup(api, client_record, statement):
    amount = the_payment(client_record).transaction.amount_paise
    party, bill = supplier_bill_for(api, client_record, amount)
    entry, amount = posted_to_a_head(api, client_record, party)
    return entry, amount, party, bill


def test_the_question_names_the_partys_open_bills_and_suggests_the_match(api, client_record, setup):
    entry, amount, party, bill = setup

    context = api.get(move_url(entry)).json()

    assert context["party"]["name"] == "Ravi Traders" and context["amount_paise"] == amount
    assert [b["id"] for b in context["bills"]] == [bill["id"]]
    assert context["proposal"]["allocations"][0]["bill"] == bill["id"]


def test_moving_it_puts_the_payment_on_the_partys_account_and_settles_the_bill(api, client_record, setup):
    entry, amount, party, bill = setup
    assert "Office Expenses" in ledgers_of(entry)

    moved = api.post(move_url(entry), {"allocations": [{"bill": bill["id"], "amount_paise": amount}]}, format="json")

    assert moved.status_code == 200, moved.content
    names = ledgers_of(entry)
    assert "Office Expenses" not in names and any("Ravi" in n for n in names)
    shown = api.get(f"{base(client_record)}/bills/{bill['id']}/").json()
    assert shown["open_paise"] == 0
    # The change is kept, like any correction of a posted entry.
    assert EntryChange.objects.filter(entry_id=entry, action="EDITED").exists()


def test_a_refused_settlement_leaves_the_entry_where_it_was(api, client_record, setup):
    entry, amount, party, bill = setup

    refused = api.post(move_url(entry), {"allocations": [{"bill": bill["id"], "amount_paise": amount + 1}]}, format="json")

    assert refused.status_code in (400, 422)
    assert "Office Expenses" in ledgers_of(entry)
    assert api.get(f"{base(client_record)}/bills/{bill['id']}/").json()["open_paise"] == amount


def test_the_double_count_item_goes_once_it_is_moved(api, client_record, setup):
    entry, amount, party, bill = setup
    before = api.get(f"{base(client_record)}/open-items/", {"kind": "payment_bypasses_bills"}).json()["items"]
    assert len(before) == 1

    api.post(move_url(entry), {"allocations": [{"bill": bill["id"], "amount_paise": amount}]}, format="json")

    assert api.get(f"{base(client_record)}/open-items/", {"kind": "payment_bypasses_bills"}).json()["items"] == []


def test_a_payment_with_no_party_cannot_be_moved(api, client_record, statement):
    row = the_payment(client_record)
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")
    api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": expense["id"], "learn": False}, format="json")
    entry = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json").json()[0]["id"]

    refused = api.post(move_url(entry), {"allocations": []}, format="json")

    assert refused.status_code == 422 and "Nobody is recorded" in refused.json()["detail"]


def test_signed_off_books_cannot_be_corrected_this_way(api, client_record, setup):
    entry, amount, party, bill = setup
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2030, 1, 1))

    refused = api.post(move_url(entry), {"allocations": [{"bill": bill["id"], "amount_paise": amount}]}, format="json")

    assert refused.status_code == 409 and refused.json()["code"] == "entry_locked"
    assert "Office Expenses" in ledgers_of(entry)


def test_a_payment_already_on_the_account_is_not_moved_again(api, client_record, setup):
    entry, amount, party, bill = setup
    body = {"allocations": [{"bill": bill["id"], "amount_paise": amount}]}
    api.post(move_url(entry), body, format="json")

    again = api.post(move_url(entry), body, format="json")

    assert again.status_code == 422 and "already on the party's account" in again.json()["detail"]


def test_a_read_only_member_may_not_move_it(api, client_record, setup, reader):
    entry, amount, party, bill = setup

    denied = sign_in(reader.user).post(move_url(entry), {"allocations": []}, format="json")

    assert denied.status_code == 403
