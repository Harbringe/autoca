"""Vouchers and the Tally XML they render to.

The sign convention is the thing to get right here. Tally accepts a voucher
whose entries are reversed without complaint -- the import succeeds, the totals
tie out, and every entry in the client's books faces the wrong way. There is no
error message anywhere in that sequence, so these tests are the error message.
"""

from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

from banking.models import StatementTransaction
from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, unresolved_for
from classify.models import LedgerAccount, LedgerGroup
from classify.seeds import seed_client
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger.tally import export_statement, render
from ledger.vouchers import (
    UnclassifiedTransactionError,
    VoucherType,
    build_voucher,
    voucher_type_for,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

COMPANY = "Ramesh Deshmukh"


@pytest.fixture
def client():
    firm = create_firm("Export Test Firm")
    return create_client(firm, COMPANY, datetime.date(2025, 4, 1))


@pytest.fixture
def statement(client):
    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        yield statement


def ledger(client, name, group=LedgerGroup.INDIRECT_EXPENSE):
    return LedgerAccount.objects.create(
        firm_id=client.firm_id, client=client, name=name, group=group
    )


def place(client, fragment, target):
    row = unresolved_for(client).filter(transaction__narration__icontains=fragment).first()
    return review(row, target)[0]


def parse(xml: str):
    return ET.fromstring(xml)


# ---------------------------------------------------------------------------
# Double entry
# ---------------------------------------------------------------------------


def test_money_out_debits_the_expense_and_credits_the_bank(client, statement):
    """A Payment: the bank goes down, the expense goes up."""
    expenses = ledger(client, "Office Expenses")
    row = place(client, "Blinkit", expenses)

    voucher = build_voucher(row)

    assert voucher.voucher_type == VoucherType.PAYMENT
    assert voucher.party_ledger == "Office Expenses"
    debit, credit = voucher.lines
    assert debit.ledger_name == "Office Expenses"
    assert debit.amount == Decimal("-530.00")
    assert debit.is_deemed_positive == "Yes"
    assert credit.ledger_name == "Axis Bank A/c 911010000004321"
    assert credit.amount == Decimal("530.00")
    assert credit.is_deemed_positive == "No"


def test_money_in_debits_the_bank_and_credits_the_income(client, statement):
    """A Receipt is the mirror image, and the half everyone gets backwards."""
    income = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    row = place(client, "102985493417", income)

    voucher = build_voucher(row)

    assert voucher.voucher_type == VoucherType.RECEIPT
    debit, credit = voucher.lines
    assert debit.ledger_name == "Axis Bank A/c 911010000004321"
    assert debit.amount == Decimal("-2.00")
    assert credit.ledger_name == "Bhim Cash Back"
    assert credit.amount == Decimal("2.00")


def test_every_voucher_balances(client, statement):
    """Tally rejects an unbalanced voucher -- after importing everything before it."""
    expenses = ledger(client, "Office Expenses")
    place(client, "Blinkit", expenses)

    for row in statement.transactions.filter(classification__ledger__isnull=False):
        voucher = build_voucher(row.classification)
        assert sum(line.amount for line in voucher.lines) == 0


# ---------------------------------------------------------------------------
# Contra
# ---------------------------------------------------------------------------


def test_a_transfer_to_the_clients_own_account_is_a_contra(client, statement):
    """Not expenditure and not income. Only the other ledger's group says so."""
    other_bank = ledger(client, "HDFC Bank A/c 50100000009876", LedgerGroup.BANK)
    row = place(client, "AXOMB20402110637", other_bank)

    assert row.is_self_transfer
    assert voucher_type_for(row) == VoucherType.CONTRA


def test_a_self_looking_narration_filed_against_an_expense_is_not_a_contra(client, statement):
    """A misfiled row must not be silently reclassified by the exporter.

    Both the narration evidence and the reviewer's ledger have to agree, or a
    supplier who shares the client's surname becomes a Contra.
    """
    expenses = ledger(client, "Professional Fees")
    row = place(client, "AXOMB20402110637", expenses)

    assert row.is_self_transfer
    assert voucher_type_for(row) == VoucherType.PAYMENT


def test_a_payment_to_a_relative_is_not_a_contra(client, statement):
    drawings = ledger(client, "Drawings", LedgerGroup.CAPITAL)
    row = place(client, "ADITYA RAMESH DESHMUKH", drawings)

    assert not row.is_self_transfer
    assert voucher_type_for(row) == VoucherType.PAYMENT


# ---------------------------------------------------------------------------
# The XML itself
# ---------------------------------------------------------------------------


def test_the_export_is_a_tally_import_envelope(client, statement):
    place(client, "Blinkit", ledger(client, "Office Expenses"))
    result = export_statement(statement, company_name=COMPANY)

    root = parse(result.xml)
    assert root.tag == "ENVELOPE"
    assert root.findtext("HEADER/TALLYREQUEST") == "Import Data"
    assert (
        root.findtext("BODY/IMPORTDATA/REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY") == COMPANY
    )


def test_dates_use_tallys_format(client, statement):
    place(client, "Blinkit", ledger(client, "Office Expenses"))
    result = export_statement(statement, company_name=COMPANY)

    dates = {node.text for node in parse(result.xml).iter("DATE")}
    assert "20260215" in dates
    assert all(len(value) == 8 and value.isdigit() for value in dates)


def test_ledger_masters_are_exported_before_the_vouchers_that_use_them(client, statement):
    """Tally reads in order and would create a later-defined ledger under a default group."""
    place(client, "Blinkit", ledger(client, "Office Expenses"))
    result = export_statement(statement, company_name=COMPANY)

    request_data = parse(result.xml).find("BODY/IMPORTDATA/REQUESTDATA")
    kinds = [list(message)[0].tag for message in request_data]

    assert "LEDGER" in kinds
    assert kinds.index("VOUCHER") > max(i for i, k in enumerate(kinds) if k == "LEDGER")


def test_ledgers_carry_their_tally_group(client, statement):
    place(client, "INTERNET TAX PAYMENT", ledger(client, "Advance Tax", LedgerGroup.DUTIES_AND_TAXES))
    result = export_statement(statement, company_name=COMPANY)

    groups = {
        node.findtext("NAME"): node.findtext("PARENT") for node in parse(result.xml).iter("LEDGER")
    }
    assert groups["Advance Tax"] == "Duties & Taxes"
    assert groups["Axis Bank A/c 911010000004321"] == "Bank Accounts"


def test_a_re_export_carries_the_same_remote_id(client, statement):
    """Without it, exporting twice after fixing one row doubles the client's books."""
    place(client, "Blinkit", ledger(client, "Office Expenses"))

    first = export_statement(statement, company_name=COMPANY)
    second = export_statement(statement, company_name=COMPANY)

    ids = [node.get("REMOTEID") for node in parse(first.xml).iter("VOUCHER")]
    assert ids == [node.get("REMOTEID") for node in parse(second.xml).iter("VOUCHER")]
    assert all(value and value.startswith("autoca-") for value in ids)


def test_unclassified_rows_are_reported_not_exported(client, statement):
    """Nine tenths of a statement while three rows wait on the client is normal."""
    place(client, "Blinkit", ledger(client, "Office Expenses"))
    result = export_statement(statement, company_name=COMPANY)

    assert result.voucher_count == 5  # four seeded interest rows, plus the reviewed one
    assert len(result.skipped) == 49
    assert not parse(result.xml).findall(".//VOUCHER[@VCHTYPE='Suspense']")


def test_exporting_an_unclassified_row_directly_is_refused(client, statement):
    row = unresolved_for(client).first()

    with pytest.raises(UnclassifiedTransactionError, match="has not been classified"):
        build_voucher(row)


def test_special_characters_in_a_payee_are_escaped(client, statement):
    """`&` in a payee name is one hand-built XML string away from a broken export."""
    awkward = ledger(client, "Smith & Sons <Suppliers>")
    place(client, "Blinkit", awkward)

    result = export_statement(statement, company_name=COMPANY)
    names = {node.text for node in parse(result.xml).iter("LEDGERNAME")}

    assert "Smith & Sons <Suppliers>" in names
    assert "&amp;" in result.xml


def test_an_unbalanced_voucher_cannot_be_rendered():
    from ledger.vouchers import Voucher, VoucherLine

    with pytest.raises(ValueError, match="does not balance"):
        Voucher(
            date="20250413",
            voucher_type=VoucherType.PAYMENT,
            narration="x",
            party_ledger="Office Expenses",
            lines=(VoucherLine("Office Expenses", Decimal("-100")), VoucherLine("Bank", Decimal("90"))),
            remote_id="autoca-test",
        )


def test_an_empty_export_is_still_a_valid_envelope(client):
    assert parse(render([], company_name=COMPANY)).tag == "ENVELOPE"


def test_narration_reaches_tally_as_the_bank_wrote_it(client, statement):
    place(client, "Blinkit", ledger(client, "Office Expenses"))
    result = export_statement(statement, company_name=COMPANY)

    narrations = {node.text for node in parse(result.xml).iter("NARRATION")}
    expected = StatementTransaction.objects.get(
        narration__icontains="Blinkit", firm_id=client.firm_id
    ).narration
    assert expected in narrations
