"""Outstanding payables and receivables, and a party's statement of account.

Both are read from the bills and allocations the ledger is checked against, so what they say must agree with
``party_position`` and must be right *as at any date*: last month's report does not change when this month's payment lands.
"""

from __future__ import annotations

import datetime

import pytest

from classify.models import LedgerAccount, LedgerGroup, PartyRole
from ledger import billing
from ledger.billing import BillInput
from ledger.models import AllocationKind, LedgerOpening
from ledger.partyreports import PAYABLES, RECEIVABLES, outstanding, party_statement
from ledger.tests.test_approval import client, firm, ledger, membership_for, senior  # noqa: F401
from ledger.tests.test_billing import books, make_party, payment_line, purchases  # noqa: F401

D = datetime.date


pytestmark = pytest.mark.django_db


def buy(client, senior, party, amount, on, reference):
    return billing.post_purchase(
        client, party, [(purchases(client), amount)], BillInput(reference=reference, bill_date=on), membership=senior
    )


def sell(client, senior, customer, amount, on, reference):
    sales = LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name="Sales", defaults={"group": LedgerGroup.SALES}
    )[0]
    return billing.post_sales(
        client, customer, [(sales, amount)], BillInput(reference=reference, bill_date=on), membership=senior
    )


def only(report, name):
    return next(p for p in report.parties if p.party.canonical_name == name)


# ---------------------------------------------------------------------------
# Outstanding
# ---------------------------------------------------------------------------


def test_each_bill_is_aged_from_its_own_date_into_the_right_bucket(books, senior):
    ravi = make_party(books)
    buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "OLD")
    buy(books, senior, ravi, 2_000_00, D(2025, 5, 15), "MID")
    buy(books, senior, ravi, 4_000_00, D(2025, 7, 20), "NEW")

    report = outstanding(books, D(2025, 8, 1), PAYABLES)

    mine = only(report, "Ravi Traders")
    assert [(b.bill.reference, b.age_days, b.bucket) for b in mine.bills] == [
        ("OLD", 122, "Over 90"), ("MID", 78, "61-90"), ("NEW", 12, "0-30"),
    ]
    assert mine.total_paise == 7_000_00
    assert (report.bucket_paise("Over 90"), report.bucket_paise("61-90"), report.bucket_paise("0-30")) == (1_000_00, 2_000_00, 4_000_00)
    assert report.total_paise == 7_000_00


def test_a_bill_dated_after_the_report_date_is_not_in_the_report(books, senior):
    buy(books, senior, make_party(books), 1_000_00, D(2025, 9, 1), "FUTURE")

    assert outstanding(books, D(2025, 8, 1), PAYABLES).parties == []


def test_a_settlement_counts_only_from_the_day_it_happened(books, senior):
    ravi = make_party(books)
    bill = buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    line = payment_line(books, ravi, 1_000_00, on=D(2025, 6, 1))
    billing.allocate(line, bill=bill, amount_paise=1_000_00)

    before = outstanding(books, D(2025, 5, 31), PAYABLES)
    after = outstanding(books, D(2025, 6, 30), PAYABLES)

    assert only(before, "Ravi Traders").total_paise == 1_000_00  # last month's report is still what it was
    assert after.parties == []


def test_a_part_payment_leaves_only_the_rest_outstanding(books, senior):
    ravi = make_party(books)
    bill = buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    billing.allocate(payment_line(books, ravi, 400_00, on=D(2025, 5, 1)), bill=bill, amount_paise=400_00)

    assert only(outstanding(books, D(2025, 6, 1), PAYABLES), "Ravi Traders").total_paise == 600_00


def test_a_debit_note_reduces_what_is_owed(books, senior):
    ravi = make_party(books)
    buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    billing.post_debit_note(
        books, ravi, [(purchases(books), 200_00)], BillInput(reference="DN-1", bill_date=D(2025, 4, 10)), membership=senior
    )

    mine = only(outstanding(books, D(2025, 5, 1), PAYABLES), "Ravi Traders")

    assert sorted(b.open_paise for b in mine.bills) == [-200_00, 1_000_00]
    assert mine.total_paise == 800_00


def test_money_held_on_account_or_as_an_advance_reduces_what_is_owed(books, senior):
    ravi = make_party(books)
    buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    billing.allocate(payment_line(books, ravi, 300_00, on=D(2025, 4, 20)), amount_paise=300_00, kind=AllocationKind.ADVANCE)

    mine = only(outstanding(books, D(2025, 5, 1), PAYABLES), "Ravi Traders")

    assert mine.bills_paise == 1_000_00 and mine.on_account_paise == -300_00 and mine.total_paise == 700_00


def test_a_party_with_only_an_advance_is_still_listed(books, senior):
    ravi = make_party(books)
    billing.party_ledger_for(ravi, side=LedgerGroup.CREDITOR)
    billing.allocate(payment_line(books, ravi, 300_00, on=D(2025, 4, 20)), amount_paise=300_00, kind=AllocationKind.ADVANCE)

    mine = only(outstanding(books, D(2025, 5, 1), PAYABLES), "Ravi Traders")

    assert mine.bills == [] and mine.total_paise == -300_00


def test_payables_and_receivables_are_kept_apart(books, senior):
    buy(books, senior, make_party(books), 1_000_00, D(2025, 4, 1), "P-1")
    sell(books, senior, make_party(books, "Mehta Stores", PartyRole.CUSTOMER, gstin=""), 5_000_00, D(2025, 4, 2), "S-1")

    payables = outstanding(books, D(2025, 5, 1), PAYABLES)
    receivables = outstanding(books, D(2025, 5, 1), RECEIVABLES)

    assert [p.party.canonical_name for p in payables.parties] == ["Ravi Traders"]
    assert [p.party.canonical_name for p in receivables.parties] == ["Mehta Stores"]
    assert (payables.total_paise, receivables.total_paise) == (1_000_00, 5_000_00)


def test_a_credit_note_reduces_what_a_customer_owes(books, senior):
    customer = make_party(books, "Mehta Stores", PartyRole.CUSTOMER, gstin="")
    sell(books, senior, customer, 5_000_00, D(2025, 4, 2), "S-1")
    sales = LedgerAccount.objects.get(client=books, name="Sales")
    billing.post_credit_note(
        books, customer, [(sales, 1_000_00)], BillInput(reference="CN-1", bill_date=D(2025, 4, 9)), membership=senior
    )

    assert only(outstanding(books, D(2025, 5, 1), RECEIVABLES), "Mehta Stores").total_paise == 4_000_00


def test_the_report_agrees_with_the_partys_position_in_the_ledger(books, senior):
    """What the report calls owed is what the ledger says, once everything is allocated."""
    ravi = make_party(books)
    bill = buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    billing.allocate(payment_line(books, ravi, 250_00, on=D(2025, 5, 1)), bill=bill, amount_paise=250_00)
    ravi.refresh_from_db()

    owed = only(outstanding(books, D(2025, 12, 31), PAYABLES), "Ravi Traders").total_paise
    position = billing.party_position(ravi)

    assert owed == 750_00 == -position.ledger_balance_paise
    assert position.reconciles


def test_an_unknown_side_is_refused(books):
    with pytest.raises(ValueError, match="side must be"):
        outstanding(books, D(2025, 5, 1), "owed")


# ---------------------------------------------------------------------------
# The statement of account
# ---------------------------------------------------------------------------


def test_a_statement_lists_every_line_with_a_running_balance(books, senior):
    ravi = make_party(books)
    bill = buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    ravi.refresh_from_db()
    payment_line(books, ravi, 400_00, on=D(2025, 5, 1))

    statement = party_statement(ravi, D(2025, 4, 1), D(2025, 6, 30))

    assert statement.opening_paise == 0
    assert [(r.voucher_type, r.debit_paise, r.credit_paise, r.balance_paise) for r in statement.rows] == [
        ("Purchase", 0, 1_000_00, -1_000_00),
        ("Payment", 400_00, 0, -600_00),
    ]
    assert statement.rows[0].bill_id == bill.pk and statement.rows[1].bill_id is None
    assert statement.closing_paise == -600_00
    assert (statement.total_debit_paise, statement.total_credit_paise) == (400_00, 1_000_00)


def test_a_statement_for_a_later_period_opens_with_what_went_before(books, senior):
    ravi = make_party(books)
    buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    ravi.refresh_from_db()
    payment_line(books, ravi, 400_00, on=D(2025, 5, 1))

    statement = party_statement(ravi, D(2025, 5, 1), D(2025, 6, 30))

    assert statement.opening_paise == -1_000_00
    assert [r.voucher_type for r in statement.rows] == ["Payment"]
    assert statement.closing_paise == -600_00


def test_the_statements_closing_balance_is_the_ledger_balance_the_bills_are_checked_against(books, senior):
    ravi = make_party(books)
    buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    ravi.refresh_from_db()
    payment_line(books, ravi, 250_00, on=D(2025, 5, 1))

    statement = party_statement(ravi, D(2025, 4, 1), D(2026, 3, 31))

    assert statement.closing_paise == billing.party_position(ravi).ledger_balance_paise


def test_an_imported_opening_balance_is_in_the_statement(books, senior):
    ravi = make_party(books)
    buy(books, senior, ravi, 1_000_00, D(2025, 4, 1), "INV-1")
    ravi.refresh_from_db()
    LedgerOpening.objects.create(
        firm_id=books.firm_id, client=books, ledger=ravi.ledger, financial_year=2025, signed_paise=-500_00
    )

    statement = party_statement(ravi, D(2025, 4, 1), D(2025, 6, 30))

    assert statement.opening_paise == -500_00
    assert statement.closing_paise == -1_500_00


def test_a_party_with_no_account_yet_has_an_empty_statement(books):
    statement = party_statement(make_party(books), D(2025, 4, 1), D(2025, 6, 30))

    assert statement.rows == [] and statement.opening_paise == 0 and statement.closing_paise == 0
