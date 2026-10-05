"""Settling bills with a payment, from the outside.

A row placed on a supplier's or customer's own account is not an expense: it pays what was owed. The API gives the review
screen the party's open bills and a suggestion, and takes back a person's decision. These go through the full stack, with
the same guarantees checked at the edge: a decision is required, a whole band never sweeps a party account in, and a row
cannot be settled against another client's bills.
"""

from __future__ import annotations

import json

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from classify.engine import review_queue
from classify.treatment import ReviewBand
from ledger.models import JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
NOBODY = "00000000-0000-0000-0000-000000000000"


def the_payment(client_record):
    return review_queue(client_record).filter(transaction__narration__icontains="AXOMB10000000001").first()


def supplier_bill_for(api, client_record, amount):
    party = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    body = voucher(
        party, purchases, cgst_paise=0, sgst_paise=0, heads=[{"ledger": purchases["id"], "amount_paise": amount}]
    )
    bill = post_bill(api, client_record, body).json()
    party = api.get(f"{base(client_record)}/parties/{party['id']}/").json()
    return party, bill


def place(api, row, ledger_id):
    response = api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": ledger_id, "learn": False}, format="json")
    assert response.status_code == 200, response.content
    return response


def approvals(api, client_record, body):
    return api.post(f"{base(client_record)}/approvals/", body, format="json")


def on_the_partys_account(api, client_record, statement):
    row = the_payment(client_record)
    amount = row.transaction.amount_paise
    party, bill = supplier_bill_for(api, client_record, amount)
    place(api, row, party["ledger"])
    return row, amount, party, bill


# ---------------------------------------------------------------------------
# The question
# ---------------------------------------------------------------------------


def test_a_row_placed_on_a_partys_account_says_so_and_suggests_the_bill(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    placed = api.get(f"{base(client_record)}/review-queue/", {"stage": "pending_approval"}).json()["results"]
    flagged = next(r for r in placed if r["id"] == str(row.pk))
    context = api.get(f"{V1}/classifications/{row.pk}/settlement/").json()

    assert flagged["on_party_account"] is True
    assert context["party"]["name"] == "Ravi Traders" and context["amount_paise"] == amount
    assert [b["reference"] for b in context["bills"]] == ["INV-1"]
    assert context["proposal"]["basis"] == "exact_one"
    assert context["proposal"]["allocations"] == [
        {"bill": bill["id"], "amount_paise": amount, "amount_display": context["amount_display"]}
    ]
    assert context["proposal"]["remainder_paise"] == 0


def test_an_ordinary_row_is_not_on_a_party_account_and_has_nothing_to_settle(api, client_record, statement):
    ordinary = review_queue(client_record).filter(ledger__isnull=False).first()
    queue = api.get(f"{base(client_record)}/review-queue/", {"stage": "pending_approval"}).json()["results"]

    assert all(r["on_party_account"] is False for r in queue)
    response = api.get(f"{V1}/classifications/{ordinary.pk}/settlement/")
    assert response.status_code == 422 and response.json()["code"] == "billing_rule"


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def test_a_row_on_a_partys_account_is_refused_without_a_settlement(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    response = approvals(api, client_record, {"classifications": [str(row.pk)]})

    assert response.status_code == 409 and response.json()["code"] == "not_approvable"
    assert "say what it settles" in response.json()["detail"]
    assert not JournalEntry.objects.filter(source_transaction=row.transaction).exists()


def test_approving_with_a_settlement_posts_the_payment_and_clears_the_bill(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    response = approvals(
        api,
        client_record,
        {"classifications": [str(row.pk)], "settlements": [
            {"classification": str(row.pk), "allocations": [{"bill": bill["id"], "amount_paise": amount}]}
        ]},
    )

    assert response.status_code == 201, response.content
    settled = api.get(f"{base(client_record)}/bills/{bill['id']}/").json()
    assert settled["open_paise"] == 0
    assert [a["amount_paise"] for a in settled["allocations"]] == [amount]
    assert settled["allocations"][0]["voucher_type"] == "Payment"


def test_what_the_bills_do_not_take_is_held_when_the_person_says_so(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)
    half = amount // 2

    response = approvals(
        api,
        client_record,
        {"classifications": [str(row.pk)], "settlements": [
            {"classification": str(row.pk), "remainder": "ON_ACCOUNT",
             "allocations": [{"bill": bill["id"], "amount_paise": half}]}
        ]},
    )

    assert response.status_code == 201, response.content
    allocations = api.get(f"{base(client_record)}/bills/{bill['id']}/").json()["allocations"]
    assert [a["amount_paise"] for a in allocations] == [half]


def test_a_settlement_that_does_not_add_up_is_refused_in_words(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    response = approvals(
        api,
        client_record,
        {"classifications": [str(row.pk)], "settlements": [
            {"classification": str(row.pk), "allocations": [{"bill": bill["id"], "amount_paise": amount - 1}]}
        ]},
    )

    assert response.status_code == 422 and response.json()["code"] == "billing_rule"
    assert "left over" in response.json()["detail"]
    assert not JournalEntry.objects.filter(source_transaction=row.transaction).exists()


def test_a_whole_band_never_sweeps_a_party_account_in(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    response = approvals(api, client_record, {"band": ReviewBand.HIGH})

    assert response.status_code == 201
    assert not JournalEntry.objects.filter(source_transaction=row.transaction).exists()


def test_settlements_do_not_go_with_a_band(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    response = approvals(
        api, client_record,
        {"band": ReviewBand.HIGH, "settlements": [{"classification": str(row.pk), "allocations": []}]},
    )

    assert response.status_code == 400 and "settlements" in response.json()["fields"]


def test_a_settlement_for_a_bill_that_is_not_this_clients_is_not_found(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)

    response = approvals(
        api, client_record,
        {"classifications": [str(row.pk)], "settlements": [
            {"classification": str(row.pk), "allocations": [{"bill": NOBODY, "amount_paise": amount}]}
        ]},
    )

    assert response.status_code == 400 and "Not bills of this client" in json.dumps(response.json())


def test_a_settlement_for_a_row_that_is_not_being_approved_is_refused(api, client_record, statement):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)
    other = review_queue(client_record).exclude(pk=row.pk).first()
    assert other is not None

    response = approvals(
        api, client_record,
        {"classifications": [str(other.pk)], "settlements": [
            {"classification": str(row.pk), "allocations": [{"bill": bill["id"], "amount_paise": amount}]}
        ]},
    )

    assert response.status_code == 400 and "not being approved" in json.dumps(response.json())


# ---------------------------------------------------------------------------
# Settling a payment that is already posted
# ---------------------------------------------------------------------------


def test_a_payment_edited_onto_a_party_account_can_be_settled_afterwards(api, client_record, statement):
    row = the_payment(client_record)
    amount = row.transaction.amount_paise
    party, bill = supplier_bill_for(api, client_record, amount)
    place(api, row, make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")["id"])
    assert approvals(api, client_record, {"classifications": [str(row.pk)]}).status_code == 201
    entry = JournalEntry.objects.get(source_transaction=row.transaction)
    moved = api.post(
        f"{V1}/journal-entries/{entry.pk}/correct/",
        {"treatment": {"ledger": party["ledger"], "learn": False}},
        format="json",
    )
    assert moved.status_code == 201, moved.content

    context = api.get(f"{V1}/journal-entries/{entry.pk}/settlement/").json()
    assert context["amount_paise"] == amount and context["already_allocated_paise"] == 0
    assert context["proposal"]["basis"] == "exact_one"

    done = api.post(
        f"{V1}/journal-entries/{entry.pk}/settle/",
        {"allocations": [{"bill": bill["id"], "amount_paise": amount}]},
        format="json",
    )
    assert done.status_code == 200, done.content
    assert done.json()["settled_paise"] == amount and done.json()["fully_allocated"] is True
    assert api.get(f"{base(client_record)}/bills/{bill['id']}/").json()["open_paise"] == 0

    again = api.get(f"{V1}/journal-entries/{entry.pk}/settlement/")
    assert again.status_code == 422 and "already fully allocated" in again.json()["detail"]


def test_a_read_only_member_cannot_settle_a_posted_payment(api, client_record, statement, reader):
    row, amount, party, bill = on_the_partys_account(api, client_record, statement)
    assert approvals(
        api, client_record,
        {"classifications": [str(row.pk)], "settlements": [
            {"classification": str(row.pk), "allocations": [{"bill": bill["id"], "amount_paise": amount}]}
        ]},
    ).status_code == 201
    entry = JournalEntry.objects.get(source_transaction=row.transaction)

    refused = sign_in(reader.user).post(f"{V1}/journal-entries/{entry.pk}/settle/", {"allocations": []}, format="json")

    assert refused.status_code == 403


def test_a_bill_voucher_cannot_be_settled_through_the_journal(api, client_record, statement):
    """Its line on the party's account is the bill itself being booked, not money that moved."""
    party, bill = supplier_bill_for(api, client_record, 100_000)

    looked = api.get(f"{V1}/journal-entries/{bill['entry']}/settlement/")
    settled = api.post(f"{V1}/journal-entries/{bill['entry']}/settle/", {"allocations": []}, format="json")

    assert looked.status_code == 409 and looked.json()["code"] == "wrong_entry_kind"
    assert settled.status_code == 409 and settled.json()["code"] == "wrong_entry_kind"
