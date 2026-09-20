"""The Tally XML export, from approved entries only.

The sign convention is the thing to get right. Tally accepts a voucher whose
entries are reversed without complaint -- the import succeeds, the totals tie,
and every entry in the client's books faces the wrong way. There is no error
message anywhere in that sequence, so these tests are the error message.
"""

from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET

import pytest

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, review_queue
from classify.models import LedgerAccount, LedgerGroup
from classify.seeds import seed_client
from classify.treatment import Treatment
from core.db.session import firm_context
from core.models import FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from ledger.approval import approve, correct
from ledger.models import JournalEntry
from ledger.tally import export_statement, remote_id_for, render

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

COMPANY = "Arjun Nair"


@pytest.fixture
def firm():
    return create_firm("Export Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, COMPANY, datetime.date(2025, 4, 1))


@pytest.fixture
def senior(firm):
    user = User.objects.create_user(email="ca@example.com", password="correct-horse-battery")
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=Role.SENIOR_CA)


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


def post(client, senior, fragment, target):
    """Classify and approve one row, returning its journal entry."""
    row = review_queue(client).filter(transaction__narration__icontains=fragment).first()
    classification = review(row, target)[0]
    return approve(classification, membership=senior).entry


def parse(xml: str):
    return ET.fromstring(xml)


def amounts_for(xml: str, ledger_name: str) -> list[str]:
    out = []
    for item in parse(xml).iter("ALLLEDGERENTRIES.LIST"):
        if item.findtext("LEDGERNAME") == ledger_name:
            out.append(item.findtext("AMOUNT"))
    return out


# ---------------------------------------------------------------------------
# Nothing unapproved gets out
# ---------------------------------------------------------------------------


def test_only_approved_entries_are_exported(client, statement, senior):
    """A classification is a suggestion. Exporting one would bypass the CA."""
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))

    result = export_statement(statement, company_name=COMPANY)

    assert result.voucher_count == 1
    assert result.unapproved == 53


def test_an_export_with_nothing_approved_is_empty_but_valid(client, statement):
    result = export_statement(statement, company_name=COMPANY)

    assert result.voucher_count == 0
    assert parse(result.xml).tag == "ENVELOPE"


# ---------------------------------------------------------------------------
# The sign convention
# ---------------------------------------------------------------------------


def test_a_payment_credits_the_bank_in_tallys_inverted_signs(client, statement, senior):
    """Debit side: ISDEEMEDPOSITIVE Yes and a negative amount. Both, together."""
    expenses = ledger(client, "Office Expenses")
    post(client, senior, "Blinkit", expenses)

    result = export_statement(statement, company_name=COMPANY)
    entries = {
        item.findtext("LEDGERNAME"): (
            item.findtext("ISDEEMEDPOSITIVE"),
            item.findtext("AMOUNT"),
        )
        for item in parse(result.xml).iter("ALLLEDGERENTRIES.LIST")
    }

    assert entries["Office Expenses"] == ("Yes", "-530.00")
    assert entries["Axis Bank A/c 0001"] == ("No", "530.00")


def test_a_receipt_debits_the_bank(client, statement, senior):
    income = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    post(client, senior, "100000000013", income)

    result = export_statement(statement, company_name=COMPANY)

    assert amounts_for(result.xml, "Axis Bank A/c 0001") == ["-2.00"]
    assert amounts_for(result.xml, "Bhim Cash Back") == ["2.00"]


def test_every_exported_voucher_sums_to_zero(client, statement, senior):
    """Tally rejects an unbalanced voucher -- after importing everything before it."""
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    post(client, senior, "INTERNET TAX PAYMENT", ledger(client, "Advance Tax", LedgerGroup.DUTIES_AND_TAXES))

    for voucher in parse(export_statement(statement, company_name=COMPANY).xml).iter("VOUCHER"):
        total = sum(
            float(item.findtext("AMOUNT")) for item in voucher.iter("ALLLEDGERENTRIES.LIST")
        )
        assert total == 0


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def test_the_export_is_a_tally_import_envelope(client, statement, senior):
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    root = parse(export_statement(statement, company_name=COMPANY).xml)

    assert root.tag == "ENVELOPE"
    assert root.findtext("HEADER/TALLYREQUEST") == "Import Data"
    assert root.findtext("BODY/IMPORTDATA/REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY") == COMPANY


def test_dates_use_tallys_format(client, statement, senior):
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    dates = {node.text for node in parse(export_statement(statement, company_name=COMPANY).xml).iter("DATE")}

    assert "20260215" in dates
    assert all(len(value) == 8 and value.isdigit() for value in dates)


def test_the_voucher_carries_its_allocated_number(client, statement, senior):
    """Auditors expect contiguous numbering, and Tally should show ours."""
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    numbers = [n.text for n in parse(export_statement(statement, company_name=COMPANY).xml).iter("VOUCHERNUMBER")]

    assert numbers == ["1"]


def test_ledger_masters_come_before_the_vouchers_that_use_them(client, statement, senior):
    """Tally reads in order and would create a later-defined ledger under a default group."""
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    request_data = parse(
        export_statement(statement, company_name=COMPANY).xml
    ).find("BODY/IMPORTDATA/REQUESTDATA")
    kinds = [list(message)[0].tag for message in request_data]

    assert "LEDGER" in kinds
    assert kinds.index("VOUCHER") > max(i for i, k in enumerate(kinds) if k == "LEDGER")


def test_ledgers_carry_their_tally_group(client, statement, senior):
    post(client, senior, "INTERNET TAX PAYMENT", ledger(client, "Advance Tax", LedgerGroup.DUTIES_AND_TAXES))
    groups = {
        node.findtext("NAME"): node.findtext("PARENT")
        for node in parse(export_statement(statement, company_name=COMPANY).xml).iter("LEDGER")
    }

    assert groups["Advance Tax"] == "Duties & Taxes"
    assert groups["Axis Bank A/c 0001"] == "Bank Accounts"


def test_re_exporting_carries_the_same_remote_id(client, statement, senior):
    """Without it, exporting twice after a correction doubles the client's books."""
    post(client, senior, "Blinkit", ledger(client, "Office Expenses"))

    first = export_statement(statement, company_name=COMPANY)
    second = export_statement(statement, company_name=COMPANY)

    ids = [node.get("REMOTEID") for node in parse(first.xml).iter("VOUCHER")]
    assert ids == [node.get("REMOTEID") for node in parse(second.xml).iter("VOUCHER")]
    assert all(value.startswith("autoca-") for value in ids)


def test_special_characters_in_a_ledger_name_are_escaped(client, statement, senior):
    """`&` in a payee name is one hand-built XML string away from a broken export."""
    post(client, senior, "Blinkit", ledger(client, "Smith & Sons <Suppliers>"))
    result = export_statement(statement, company_name=COMPANY)

    assert "Smith & Sons <Suppliers>" in {
        node.text for node in parse(result.xml).iter("LEDGERNAME")
    }
    assert "&amp;" in result.xml


def test_an_empty_export_is_still_a_valid_envelope():
    assert parse(render([], company_name=COMPANY)).tag == "ENVELOPE"


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def sign_off_through(client, entry):
    from core.models import Client

    Client.objects.filter(pk=client.pk).update(signed_off_through=entry.entry_date)


def test_a_superseded_entry_is_not_exported(client, statement, senior):
    """The correction carries both the reversal and the new position.

    Exporting the original as well would double-count it. It stays visible in
    this system, which is where company law requires it to be.
    """
    original = post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    sign_off_through(client, original)
    corrected = correct(
        original, membership=senior, treatment=Treatment(ledger=ledger(client, "Staff Welfare"))
    )

    result = export_statement(statement, company_name=COMPANY)
    ids = {node.get("REMOTEID") for node in parse(result.xml).iter("VOUCHER")}

    assert ids == {remote_id_for(corrected)}
    assert remote_id_for(original) not in ids
    assert JournalEntry.objects.count() == 2


def test_a_correction_exports_as_its_own_voucher(client, statement, senior):
    """It must not overwrite the entry it replaced in Tally, so its id differs."""
    original = post(client, senior, "Blinkit", ledger(client, "Office Expenses"))
    sign_off_through(client, original)
    corrected = correct(
        original, membership=senior, treatment=Treatment(ledger=ledger(client, "Staff Welfare"))
    )

    assert remote_id_for(corrected) != remote_id_for(original)
