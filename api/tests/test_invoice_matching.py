"""An invoice and the bank row that paid it are settled against each other when they are plainly one and the same."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from api.tests.test_invoices_api import SUPPLIER
from api.tests.test_settlement_api import the_payment
from classify.models import ClassificationMethod
from core.db.session import firm_context
from ledger import matching
from ledger.models import Bill, EntryMarker, JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def book_bill(api, client_record, amount, name="Ravi Traders", on=None):
    party = make_party(api, client_record, name=name, gstin=SUPPLIER)
    purchases = make_ledger(api, client_record)
    body = voucher(
        party, purchases, cgst_paise=0, sgst_paise=0, bill_date=(on or the_payment(client_record).transaction.value_date).isoformat(),
        heads=[{"ledger": purchases["id"], "amount_paise": amount}],
    )
    bill = post_bill(api, client_record, body).json()
    return party, bill


def attribute_row_to(client_record, row, party_id):
    with firm_context(client_record.firm_id):
        classification = row.transaction.classification
        classification.party_id = party_id
        classification.method = ClassificationMethod.RULE
        classification.save(update_fields=["party", "method"])


def test_a_row_that_is_the_parties_payment_of_exactly_the_bills_amount_is_settled_against_it(api, client_record, statement):
    row = the_payment(client_record)
    party, bill = book_bill(api, client_record, row.transaction.amount_paise)
    attribute_row_to(client_record, row, party["id"])

    with firm_context(client_record.firm_id):
        settled = matching.match_client(client_record)

    assert settled == 1
    fresh = api.get(f"{base(client_record)}/bills/{bill['id']}/").json()
    assert fresh["open_paise"] == 0 and [a["amount_paise"] for a in fresh["allocations"]] == [row.transaction.amount_paise]
    with firm_context(client_record.firm_id):
        entry = JournalEntry.objects.get(source_transaction=row.transaction)
        assert entry.marker == EntryMarker.AI_POSTED and entry.approved_by_id is None


def test_a_different_amount_is_never_settled(api, client_record, statement):
    row = the_payment(client_record)
    party, bill = book_bill(api, client_record, row.transaction.amount_paise - 1)
    attribute_row_to(client_record, row, party["id"])

    with firm_context(client_record.firm_id):
        assert matching.match_client(client_record) == 0
        assert not JournalEntry.objects.filter(source_transaction=row.transaction).exists()


def test_a_row_nobody_ties_to_the_party_is_not_guessed(api, client_record, statement):
    row = the_payment(client_record)
    book_bill(api, client_record, row.transaction.amount_paise, name="Somebody Unrelated Pvt Ltd")

    with firm_context(client_record.firm_id):
        assert matching.match_client(client_record) == 0


def test_two_bills_that_the_same_row_could_pay_are_left_for_a_person(api, client_record, statement):
    row = the_payment(client_record)
    party, _ = book_bill(api, client_record, row.transaction.amount_paise)
    purchases = make_ledger(api, client_record, "Other Purchases", "PURCHASE")
    second = voucher(
        party, purchases, reference="INV-2", cgst_paise=0, sgst_paise=0, bill_date=row.transaction.value_date.isoformat(),
        heads=[{"ledger": purchases["id"], "amount_paise": row.transaction.amount_paise}],
    )
    assert post_bill(api, client_record, second).status_code == 201
    attribute_row_to(client_record, row, party["id"])

    with firm_context(client_record.firm_id):
        assert matching.match_client(client_record) == 0
        assert Bill.objects.filter(client=client_record).count() == 2


def test_a_row_a_person_has_placed_is_left_alone(api, client_record, statement):
    row = the_payment(client_record)
    party, _ = book_bill(api, client_record, row.transaction.amount_paise)
    with firm_context(client_record.firm_id):
        classification = row.transaction.classification
        classification.party_id = party["id"]
        classification.method = ClassificationMethod.REVIEWED
        classification.save(update_fields=["party", "method"])

        assert matching.match_client(client_record) == 0
