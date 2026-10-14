"""Pairing a client's transfers between its own accounts, against real rows (the pure rules are in test_transfers)."""

from __future__ import annotations

import pytest

from classify.engine import review, review_queue
from classify.models import ClassificationMethod, TransactionClassification
from classify.seeds import contra_ledger_for
from classify.transfers import pair_own_transfers
from ledger.approval import approve
from ledger.models import JournalEntry, VoucherType
from ledger.tests.test_approval import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    membership_for,
    senior,
    statement,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _arrival(client, outgoing, narration):
    """A second account whose statement shows the same amount arriving the same day, with the given narration."""
    from banking.models import BankAccount, Statement, StatementTransaction
    from documents.models import Document, DocumentKind

    txn = outgoing.transaction
    other = BankAccount(firm_id=client.firm_id, client=client, bank_code="HDFC", ledger_name="HDFC Bank A/c 9876")
    other.set_account_number("50100000009876")
    other.save()
    document = Document.objects.create(firm_id=client.firm_id, client=client, kind=DocumentKind.BANK_STATEMENT, sha256="pair-test")
    statement = Statement.objects.create(
        firm_id=client.firm_id, document=document, bank_account=other, period_start=txn.value_date, period_end=txn.value_date,
        opening_balance_paise=0, closing_balance_paise=txn.amount_paise, total_debit_paise=0, total_credit_paise=txn.amount_paise,
        transaction_count=1,
    )
    arriving = StatementTransaction.objects.create(
        firm_id=client.firm_id, statement=statement, bank_account=other, row_number=1, value_date=txn.value_date,
        narration=narration, credit_paise=txn.amount_paise, balance_paise=txn.amount_paise, dedupe_hash="pair-row-1",
    )
    return other, TransactionClassification.objects.create(firm_id=client.firm_id, transaction=arriving)


def _outgoing(client):
    return review_queue(client).filter(transaction__narration__icontains="AXOMB10000000001").first()


def test_both_sides_of_a_transfer_are_placed_in_each_others_account_and_post_as_one_contra(client, statement, senior):
    outgoing = _outgoing(client)
    other, arriving = _arrival(client, outgoing, "DEP TFR UPI/CR/AXOMB10000000001/Self")

    pairs = pair_own_transfers(client)

    assert [p.strength for p in pairs] == ["reference"]
    outgoing.refresh_from_db()
    arriving.refresh_from_db()
    assert outgoing.ledger == contra_ledger_for(other) and arriving.ledger == contra_ledger_for(statement.bank_account)
    assert outgoing.is_self_transfer and arriving.is_self_transfer
    assert outgoing.method == ClassificationMethod.RULE and outgoing.confidence >= 0.9

    first = approve(outgoing, membership=senior)
    second = approve(arriving, membership=senior)
    assert first.entry.voucher_type == VoucherType.CONTRA and second.mirrored
    assert JournalEntry.objects.filter(voucher_type=VoucherType.CONTRA).count() == 1


def test_a_row_a_person_already_placed_is_left_alone(client, statement, senior):
    outgoing = _outgoing(client)
    other, arriving = _arrival(client, outgoing, "DEP TFR UPI/CR/AXOMB10000000001/Self")
    somewhere = ledger(client, "Somewhere Else")
    review(outgoing, somewhere, learn=False)

    assert pair_own_transfers(client) == []
    outgoing.refresh_from_db()
    assert outgoing.ledger == somewhere and outgoing.method == ClassificationMethod.REVIEWED


def test_running_it_twice_changes_nothing_the_second_time(client, statement):
    outgoing = _outgoing(client)
    _arrival(client, outgoing, "DEP TFR UPI/CR/AXOMB10000000001/Self")
    assert len(pair_own_transfers(client)) == 1
    assert pair_own_transfers(client) == []


def test_a_preview_changes_nothing(client, statement):
    outgoing = _outgoing(client)
    _arrival(client, outgoing, "DEP TFR UPI/CR/AXOMB10000000001/Self")
    assert len(pair_own_transfers(client, apply=False)) == 1
    outgoing.refresh_from_db()
    assert outgoing.method != ClassificationMethod.RULE


def test_an_arrival_with_nothing_in_common_is_not_paired(client, statement):
    outgoing = _outgoing(client)
    _arrival(client, outgoing, "DEP BY SOMEONE ELSE")
    assert pair_own_transfers(client) == []
