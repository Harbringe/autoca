"""A supplier's payment goes on the supplier's own account, as a Tally Payment voucher books it, not in Purchases.

The model is never shown a party's account (its name is the party's), so it books a payment to a textile supplier to Purchases.
``place_on_party_accounts`` moves such rows onto the party's account as a proposal; approving one with no bill open holds it on
account, and the bank's spelling is remembered for the party.
"""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger
from classify.engine import review_queue
from classify.models import ClassificationMethod, LedgerAccount, Party, PartyAlias
from classify.party_discovery import place_on_party_accounts
from classify.treatment import ReviewBand, band_for
from core.db.session import firm_context
from ledger.models import AllocationKind, BillAllocation, JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def a_payment(client_record):
    return review_queue(client_record).filter(transaction__debit_paise__gt=0, is_self_transfer=False).first()


def booked_by_the_model(row, ledger_id, counterparty):
    row.counterparty = counterparty
    row.ledger_id = ledger_id
    row.method = ClassificationMethod.LLM
    row.confidence = 0.8
    row.review_band = band_for(0.8)
    row.party = None
    row.save()
    return row


def supplier_account(client_record, name):
    with firm_context(client_record.firm_id):
        ledger = LedgerAccount.objects.create(firm_id=client_record.firm_id, client=client_record, name=name, group="CREDITOR")
        Party.objects.create(firm_id=client_record.firm_id, client=client_record, canonical_name=name, role="VENDOR", ledger=ledger)
    return ledger


def test_a_payment_the_model_put_in_purchases_moves_to_the_supplier_the_bank_name_reads_as(api, client_record, statement):
    purchases = make_ledger(api, client_record, "Purchase 5%", "PURCHASE")
    account = supplier_account(client_record, "Sample Silk Mills Surat")
    row = booked_by_the_model(a_payment(client_record), purchases["id"], "SAMPLE SILK MILL")

    with firm_context(client_record.firm_id):
        moved = place_on_party_accounts(client_record)
    row.refresh_from_db()

    assert moved == {row.pk}
    assert row.ledger_id == account.pk and row.party.ledger_id == account.pk
    assert row.method == ClassificationMethod.RULE and row.review_band == ReviewBand.ADVISED
    assert "reads as your ledger" in row.rationale


def test_an_expense_the_model_read_as_one_stays_an_expense(api, client_record, statement):
    power = make_ledger(api, client_record, "Light Bill", "INDIRECT_EXPENSE")
    supplier_account(client_record, "Sample Power Company Nanded")
    row = booked_by_the_model(a_payment(client_record), power["id"], "SAMPLE POWER COMPANY")

    with firm_context(client_record.firm_id):
        assert place_on_party_accounts(client_record) == set()
    row.refresh_from_db()
    assert str(row.ledger_id) == power["id"]


def test_a_payment_on_a_supplier_with_no_open_bill_is_approved_on_account_and_the_spelling_remembered(api, client_record, statement):
    purchases = make_ledger(api, client_record, "Purchase 5%", "PURCHASE")
    account = supplier_account(client_record, "Sample Silk Mills Surat")
    row = booked_by_the_model(a_payment(client_record), purchases["id"], "SAMPLE SILK MILL")
    with firm_context(client_record.firm_id):
        place_on_party_accounts(client_record)

    queue = api.get(f"{base(client_record)}/review-queue/", {"stage": "pending_approval"}).json()["results"]
    shown = next(r for r in queue if r["id"] == str(row.pk))
    assert shown["on_party_account"] is True and shown["needs_settlement"] is False

    response = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")

    assert response.status_code == 201, response.content
    entry = JournalEntry.objects.get(source_transaction=row.transaction)
    line = entry.lines.get(ledger_account=account)
    assert [(a.kind, a.amount_paise) for a in BillAllocation.objects.filter(line=line)] == [
        (AllocationKind.ON_ACCOUNT, row.transaction.amount_paise)
    ]
    assert PartyAlias.objects.filter(party__ledger=account, alias_display="SAMPLE SILK MILL").exists()


def test_a_known_party_is_sure_enough_to_go_with_the_high_band(api, client_record, statement):
    purchases = make_ledger(api, client_record, "Purchase 5%", "PURCHASE")
    account = supplier_account(client_record, "Sample Fabrics")
    row = booked_by_the_model(a_payment(client_record), purchases["id"], "SAMPLE FABRICS")
    with firm_context(client_record.firm_id):
        row.party = account.party_record
        row.party_resolution = "AUTO"
        row.save(update_fields=["party", "party_resolution"])
        place_on_party_accounts(client_record)
    row.refresh_from_db()
    assert row.review_band == ReviewBand.HIGH

    response = api.post(f"{base(client_record)}/approvals/", {"band": ReviewBand.HIGH}, format="json")

    assert response.status_code == 201, response.content
    assert JournalEntry.objects.filter(source_transaction=row.transaction, lines__ledger_account=account).exists()
