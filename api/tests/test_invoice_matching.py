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
        classification.party_id = party_id  # still unplaced: only whose it is is known
        # The fixture's payee has the account holder's own name, so it reads as a transfer to self; this one is not.
        classification.is_self_transfer = False
        classification.save(update_fields=["party", "is_self_transfer"])


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
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")
    with firm_context(client_record.firm_id):
        classification = row.transaction.classification
        classification.party_id = party["id"]
        classification.ledger_id = expense["id"]
        classification.method = ClassificationMethod.REVIEWED
        classification.needs_review = False
        classification.save(update_fields=["party", "ledger", "method", "needs_review"])

        assert matching.match_client(client_record) == 0


def test_a_receipt_net_of_the_tds_the_customer_deducts_settles_the_bill_in_full(api, client_record, statement):
    # The statement's NEFT credit of 7,403.75 is the bill (taxable 8,226.75) less 10% TDS (822.675, to the rupee: 823).
    with firm_context(client_record.firm_id):
        from classify.models import TransactionClassification

        row = TransactionClassification.objects.get(transaction__credit_paise=740_375, transaction__value_date__month=9)
    party = make_party(api, client_record, name="Sovereign Clients", role="CUSTOMER", gstin=SUPPLIER)
    api.patch(f"{base(client_record)}/parties/{party['id']}/", {"tds_section": "194J"}, format="json")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    body = voucher(
        party, sales, kind="SALES", reference="S-1", cgst_paise=0, sgst_paise=0, bill_date=row.transaction.value_date.isoformat(),
        heads=[{"ledger": sales["id"], "amount_paise": 822_675}],
    )
    bill = post_bill(api, client_record, body).json()
    assert bill["total_paise"] == 822_675
    attribute_row_to(client_record, row, party["id"])

    with firm_context(client_record.firm_id):
        settled = matching.match_client(client_record)
        entry = JournalEntry.objects.get(source_transaction=row.transaction)
        lines = {line.ledger_account.name: (line.direction, line.amount_paise) for line in entry.lines.select_related("ledger_account")}

    assert settled == 1
    assert lines["TDS Receivable"] == ("DR", 82_300)
    assert lines["Sovereign Clients"] == ("CR", 822_675)
    assert api.get(f"{base(client_record)}/bills/{bill['id']}/").json()["open_paise"] == 0


def test_the_review_screen_is_told_where_a_placement_came_from(api, client_record, statement):
    row = the_payment(client_record)
    party, _ = book_bill(api, client_record, row.transaction.amount_paise)
    attribute_row_to(client_record, row, party["id"])
    with firm_context(client_record.firm_id):
        assert matching.match_client(client_record) == 1

    detail = api.get(f"/api/v1/classifications/{row.pk}/").json()

    assert detail["memory"]["kind"] == "matched" and "Matched to" in detail["memory"]["note"]


def test_every_report_line_says_which_ledger_it_is_so_it_can_be_opened(api, client_record, statement):
    row = the_payment(client_record)
    party, bill = book_bill(api, client_record, row.transaction.amount_paise)
    fy = 2025 if row.transaction.value_date.month >= 4 else 2024

    report = api.get(f"{base(client_record)}/reports/trial-balance/", {"fy": fy}).json()

    by_name = {line["name"]: line["ledger"] for line in report["rows"]}
    ledgers = {l["name"]: l["id"] for l in api.get(f"{base(client_record)}/ledgers/").json()["results"]}
    assert by_name["Ravi Traders"] == ledgers["Ravi Traders"]
    assert by_name.get("Difference in opening balances", None) is None
