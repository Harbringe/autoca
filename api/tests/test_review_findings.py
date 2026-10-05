"""Regressions from the CA-at-the-API review of a real year's bank statement.

Each test is a thing a senior CA would not sign the books over. They go through the API, as
the reviewer did, so what they guard is what a person met and not an internal detail.
"""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from api.tests.test_api import V1, ledger
from classify.engine import review_queue
from classify.models import LedgerGroup, Party
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.models import Role
from ledger.models import Direction, JournalEntry, JournalLine

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def approve_high(api, client_record):
    return api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")


def bank_net(client_record) -> int:
    """Debits minus credits on the client's bank ledger, over every entry, corrected or not."""
    lines = JournalLine.objects.filter(entry__client=client_record, ledger_account__group=LedgerGroup.BANK)
    return sum(line.amount_paise if line.direction == Direction.DEBIT else -line.amount_paise for line in lines)


# --- A1-001: a name that is taken is refused, readably ------------------------------------------


def test_a_ledger_name_that_exists_is_refused_not_a_server_error(api, client_record):
    url = f"{V1}/clients/{client_record.pk}/ledgers/"
    assert api.post(url, {"name": "Salary Received", "group": "INDIRECT_INCOME"}, format="json").status_code == 201

    same = api.post(url, {"name": "Salary Received", "group": "INDIRECT_INCOME"}, format="json")
    other_case = api.post(url, {"name": "salary received", "group": "INDIRECT_INCOME"}, format="json")

    for response in (same, other_case):
        assert response.status_code == 400
        assert "already has a ledger" in response.json()["fields"]["name"][0]


def test_a_party_name_that_exists_is_refused_not_a_server_error(api, client_record):
    url = f"{V1}/clients/{client_record.pk}/parties/"
    assert api.post(url, {"canonical_name": "Ramesh Traders"}, format="json").status_code == 201

    for name in ("Ramesh Traders", "ramesh traders"):
        response = api.post(url, {"canonical_name": name}, format="json")
        assert response.status_code == 400
        assert "already has a party" in response.json()["fields"]["canonical_name"][0]
    assert Party.objects.filter(client=client_record).count() == 1


def test_a_ledger_cannot_be_renamed_onto_another_in_a_different_case(api, client_record):
    with firm_context(client_record.firm_id):
        ledger(client_record, "Rent")
        other = ledger(client_record, "Office Costs")

    response = api.patch(f"{V1}/clients/{client_record.pk}/ledgers/{other.pk}/", {"name": "RENT"}, format="json")

    assert response.status_code == 400


# --- A1-003: "this entry only" means this entry only; the bank is never the other side -----------


def test_a_one_off_correction_changes_only_the_entry_named(api, client_record, statement):
    cashback = ledger(client_record, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    elsewhere = ledger(client_record, "Other Income", LedgerGroup.INDIRECT_INCOME)
    row = review_queue(client_record).filter(counterparty="NPCI BHIM").first()
    api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": str(cashback.pk), "learn": True}, format="json")
    approve_high(api, client_record)
    posted = [
        e for e in JournalEntry.objects.filter(client=client_record)
        if any(line.ledger_account_id == cashback.pk for line in e.lines.all())
    ]
    assert len(posted) >= 2, "the fixture should have several entries in that ledger"

    response = api.post(
        f"{V1}/journal-entries/{posted[0].pk}/correct/",
        {"treatment": {"ledger": str(elsewhere.pk), "learn": False}},
        format="json",
    )

    assert response.status_code == 201
    for entry in posted[1:]:
        ledgers = {line.ledger_account_id for line in JournalEntry.objects.get(pk=entry.pk).lines.all()}
        assert cashback.pk in ledgers and elsewhere.pk not in ledgers


def test_an_entry_cannot_be_corrected_into_the_bank_account_it_came_from(api, client_record, statement):
    approve_high(api, client_record)
    entry = JournalEntry.objects.filter(client=client_record).first()
    bank = JournalLine.objects.filter(entry=entry, ledger_account__group=LedgerGroup.BANK).first().ledger_account

    response = api.post(
        f"{V1}/journal-entries/{entry.pk}/correct/", {"treatment": {"ledger": str(bank.pk)}}, format="json"
    )

    assert response.status_code == 400
    assert "bank account" in response.json()["detail"]


# --- A1-004: correcting a correction keeps the reversal, so the original is not counted twice ----


def test_correcting_a_correction_after_a_reopen_does_not_count_the_original_twice(api, client_record, statement):
    approve_high(api, client_record)
    original = JournalEntry.objects.filter(client=client_record).order_by("entry_date").first()
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=original.entry_date)
    first = ledger(client_record, "Adjustment One", LedgerGroup.INDIRECT_EXPENSE)
    second = ledger(client_record, "Adjustment Two", LedgerGroup.INDIRECT_EXPENSE)
    bank_before = bank_net(client_record)

    correction = api.post(
        f"{V1}/journal-entries/{original.pk}/correct/", {"treatment": {"ledger": str(first.pk)}}, format="json"
    ).json()
    assert correction["supersedes"] == str(original.pk)
    assert bank_net(client_record) == bank_before, "reversal plus new entry leaves the bank as it was"

    # The correction is dated after sign-off, so it is still open to change. Change it again.
    again = api.post(
        f"{V1}/journal-entries/{correction['id']}/correct/", {"treatment": {"ledger": str(second.pk)}}, format="json"
    )

    assert again.status_code == 201
    assert bank_net(client_record) == bank_before, "the bank must not move: the original is still in the books"
    entry = JournalEntry.objects.get(pk=correction["id"])
    lines = list(entry.lines.all())
    assert len(lines) == 4, "reversal of the original (2 lines) plus the new treatment (2 lines)"
    assert sum(line.amount_paise for line in lines if line.direction == Direction.DEBIT) == sum(
        line.amount_paise for line in lines if line.direction == Direction.CREDIT
    )


# --- A1-006: a posted row is the record; it cannot be re-placed from under its entry --------------


def test_a_posted_row_cannot_be_placed_or_given_a_party_again(api, client_record, statement):
    approve_high(api, client_record)
    entry = JournalEntry.objects.filter(client=client_record).first()
    row = entry.source_transaction.classification
    elsewhere = ledger(client_record, "Other Income", LedgerGroup.INDIRECT_INCOME)
    party = Party.objects.create(firm_id=client_record.firm_id, client=client_record, canonical_name="Someone")

    placed = api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": str(elsewhere.pk)}, format="json")
    confirmed = api.post(f"{V1}/classifications/{row.pk}/confirm-party/", {"party": str(party.pk)}, format="json")

    for response in (placed, confirmed):
        assert response.status_code == 409
        assert response.json()["code"] == "already_posted"
        assert "correct the entry" in response.json()["detail"]
    row.refresh_from_db()
    assert row.ledger_id != elsewhere.pk


# --- A1-009: a locked entry says it is locked, to whoever tries it -------------------------------


def test_staff_correcting_a_signed_off_entry_is_told_it_is_locked(client_record, statement, api, staff):
    approve_high(api, client_record)
    entry = JournalEntry.objects.filter(client=client_record).order_by("entry_date").first()
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=entry.entry_date)
    elsewhere = ledger(client_record, "Other Income", LedgerGroup.INDIRECT_INCOME)
    from core.models import Client

    Client.objects.filter(pk=client_record.pk).update(lead=member(client_record.firm, Role.SENIOR_CA, "lead@example.test"))

    response = sign_in(staff.user).post(
        f"{V1}/journal-entries/{entry.pk}/correct/", {"treatment": {"ledger": str(elsewhere.pk)}}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "entry_locked"
    assert "signed off through" in response.json()["detail"]


def test_deciding_a_proposal_is_refused_in_words_about_proposals(staff_api, client_record):
    from classify.models import LedgerStatus

    with firm_context(client_record.firm_id):
        proposed = ledger(client_record, "Proposed Ledger")
        proposed.status = LedgerStatus.PROPOSED
        proposed.save()

    response = staff_api.post(f"{V1}/clients/{client_record.pk}/ledgers/{proposed.pk}/reject/")

    assert response.status_code == 403
    assert "sign off" not in response.json()["detail"]
    assert "proposed ledgers" in response.json()["detail"]

