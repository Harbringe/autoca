"""Books brought from Tally keep TDS on ledgers of their own ("TDS on Contract 194C"): the TDS pages read them as TDS Payable."""

from __future__ import annotations

import datetime

import pytest

from classify.models import LedgerGroup
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger import tds
from ledger.tests.support import make_ledger, post


@pytest.mark.parametrize(
    ("name", "section"),
    [
        ("TDS 194-C", "194C"),
        ("TDS Payable u/s 194J", "194J"),
        ("TDS @2% 194C", "194C"),
        ("TDS 194(I)(b) Rent", "194I"),
        ("TDS 194IA", "194IA"),
        ("TDS - 194 Q", "194Q"),
        ("TDS 192", "192"),
        ("TDS on Contract", "194C"),
        ("TDS on Professional Fees", "194J"),
        ("TDS on Rent", "194I"),
        ("TDS on Salary", "192"),
        ("TDS Payable", ""),
    ],
)
def test_the_section_is_read_from_the_ledger_name(name, section):
    assert tds.section_from_name(name) == section


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_tally_named_tds_ledgers_are_counted_and_tds_receivable_is_not():
    client = create_client(create_firm("Tally TDS Firm"), "Sample Works", datetime.date(2025, 4, 1))
    with firm_context(client.firm_id):
        works = make_ledger(client, "Contract Work", LedgerGroup.DIRECT_EXPENSE)
        contract = make_ledger(client, "TDS on Contract 194C", LedgerGroup.DUTIES_AND_TAXES)
        fees = make_ledger(client, "TDS on Professional Fees", LedgerGroup.DUTIES_AND_TAXES)
        receivable = make_ledger(client, "TDS Receivable", LedgerGroup.CURRENT_ASSET)
        bank = make_ledger(client, "Sample Bank A/c", LedgerGroup.BANK)
        post(client, datetime.date(2025, 5, 10), works, contract, 2_000_00)
        post(client, datetime.date(2025, 5, 20), works, fees, 5_000_00)
        post(client, datetime.date(2025, 5, 25), receivable, bank, 900_00)

        assert {ledger.name for ledger in tds.payable_ledgers(client)} == {"TDS on Contract 194C", "TDS on Professional Fees"}
        months = {(m.section, m.month): m.deducted_paise for m in tds.position(client)}
        assert months == {("194C", 5): 2_000_00, ("194J", 5): 5_000_00}

        # The deposit from the bank is a debit on the same ledger, waiting for its challan.
        payment = post(client, datetime.date(2025, 6, 5), contract, bank, 2_000_00)
        assert [e.pk for e, _ in tds.payments_without_challan(client)] == [payment.pk]
