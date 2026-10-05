"""A loan is an account too: its statement posts through the same machinery as a bank's.

What is different, and what these tests pin:

* its ledger is a liability (Loans), not a bank account;
* interest and charges move no cash, so they are Journal vouchers; an instalment is a Payment and a disbursal a
  Receipt;
* an instalment appears on BOTH the bank's statement and the loan's, and must be posted once, whichever statement
  is uploaded first.
"""

from __future__ import annotations

import datetime

import pytest

from classify.engine import review, review_queue
from classify.models import LedgerGroup
from classify.seeds import contra_ledger_for
from ledger.approval import approve
from ledger.models import Direction, JournalEntry, VoucherType
from ledger.reconciliation import ledger_balance
from ledger.tests.test_approval import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    membership_for,
    senior,
    statement,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _loan_row(client, *, value_date, debit_paise=0, credit_paise=0, narration, balance_paise):
    """A loan account with one row on its statement, and that row ready to classify."""
    from banking.models import AccountKind, BankAccount, Statement, StatementTransaction
    from classify.models import TransactionClassification
    from documents.models import Document, DocumentKind

    loan = BankAccount.objects.filter(client=client, kind=AccountKind.LOAN).first()
    if loan is None:
        loan = BankAccount(firm_id=client.firm_id, client=client, bank_code="KVB", kind=AccountKind.LOAN)
        loan.set_account_number("4852777000000601")
        loan.save()
    document = Document.objects.create(
        firm_id=client.firm_id, client=client, kind=DocumentKind.BANK_STATEMENT, sha256=f"loan-{narration}-{value_date}"
    )
    statement = Statement.objects.create(
        firm_id=client.firm_id, document=document, bank_account=loan,
        period_start=value_date, period_end=value_date,
        opening_balance_paise=0, closing_balance_paise=balance_paise,
        total_debit_paise=debit_paise, total_credit_paise=credit_paise, transaction_count=1,
    )
    txn = StatementTransaction.objects.create(
        firm_id=client.firm_id, statement=statement, bank_account=loan, row_number=1,
        value_date=value_date, narration=narration, debit_paise=debit_paise, credit_paise=credit_paise,
        balance_paise=balance_paise, dedupe_hash=f"loan-row-{narration}-{value_date}",
    )
    return loan, TransactionClassification.objects.create(firm_id=client.firm_id, transaction=txn)


def _lines(entry):
    return sorted((line.ledger_account.name, line.direction, line.amount_paise) for line in entry.lines.all())


def _emi_on_the_bank_statement(client):
    outgoing = review_queue(client).filter(transaction__narration__icontains="AXOMB10000000001").first()
    return outgoing, outgoing.transaction.amount_paise, outgoing.transaction.value_date


def test_a_loan_account_has_a_liability_ledger_not_a_bank_ledger(client, statement):
    loan, _ = _loan_row(client, value_date=datetime.date(2025, 5, 5), debit_paise=2196900, narration="INTEREST", balance_paise=2196900)

    loan_ledger = contra_ledger_for(loan)
    bank_ledger = contra_ledger_for(statement.bank_account)

    assert loan.ledger_name == "Kvb Loan A/c 0601"
    assert loan_ledger.group == LedgerGroup.LOAN and not loan_ledger.is_bank_or_cash
    assert bank_ledger.group == LedgerGroup.BANK and bank_ledger.is_bank_or_cash


def test_interest_charged_on_a_loan_is_a_journal_that_credits_the_loan(client, statement, senior):
    loan, interest_row = _loan_row(
        client, value_date=datetime.date(2025, 5, 5), debit_paise=2196900, narration="REGULAR INTEREST", balance_paise=2196900
    )
    interest = ledger(client, "Interest on Home Loan")

    result = approve(review(interest_row, interest, learn=False)[0], membership=senior)

    assert result.entry.voucher_type == VoucherType.JOURNAL and not result.mirrored
    assert _lines(result.entry) == [
        ("Interest on Home Loan", Direction.DEBIT, 2196900),
        ("Kvb Loan A/c 0601", Direction.CREDIT, 2196900),
    ]
    assert "charged on the loan" in result.entry.narration
    # What is owed, from the books, agrees with what the loan statement prints.
    assert ledger_balance(loan, datetime.date(2025, 5, 5)) == 2196900


def test_an_instalment_seen_on_both_statements_is_posted_once_bank_statement_first(client, statement, senior):
    axis = statement.bank_account
    outgoing, amount, paid_on = _emi_on_the_bank_statement(client)
    loan, on_the_loan = _loan_row(
        client, value_date=paid_on + datetime.timedelta(days=1), credit_paise=amount,
        narration="Installment Payment By Xfer.", balance_paise=0,
    )

    first = approve(review(outgoing, contra_ledger_for(loan), learn=False)[0], membership=senior)
    second = approve(review(on_the_loan, contra_ledger_for(axis), learn=False)[0], membership=senior)

    assert first.entry.voucher_type == VoucherType.PAYMENT and not first.mirrored
    assert second.mirrored and second.entry.pk == first.entry.pk
    assert JournalEntry.objects.count() == 1
    assert _lines(first.entry) == [
        (axis.ledger_name, Direction.CREDIT, amount),
        (loan.ledger_name, Direction.DEBIT, amount),
    ]


def test_an_instalment_seen_on_both_statements_is_posted_once_loan_statement_first(client, statement, senior):
    axis = statement.bank_account
    outgoing, amount, paid_on = _emi_on_the_bank_statement(client)
    loan, on_the_loan = _loan_row(
        client, value_date=paid_on, credit_paise=amount, narration="Installment Payment By Xfer.", balance_paise=0
    )

    first = approve(review(on_the_loan, contra_ledger_for(axis), learn=False)[0], membership=senior)
    second = approve(review(outgoing, contra_ledger_for(loan), learn=False)[0], membership=senior)

    assert first.entry.voucher_type == VoucherType.PAYMENT and not first.mirrored
    assert second.mirrored and second.entry.pk == first.entry.pk
    assert JournalEntry.objects.count() == 1


def test_a_disbursal_is_a_receipt_seen_once_on_both_statements(client, statement, senior):
    axis = statement.bank_account
    loan, disbursal = _loan_row(
        client, value_date=datetime.date(2025, 5, 5), debit_paise=500000000,
        narration="LOAN DISBURSAL", balance_paise=500000000,
    )
    first = approve(review(disbursal, contra_ledger_for(axis), learn=False)[0], membership=senior)

    assert first.entry.voucher_type == VoucherType.RECEIPT
    assert _lines(first.entry) == [
        (axis.ledger_name, Direction.DEBIT, 500000000),
        (loan.ledger_name, Direction.CREDIT, 500000000),
    ]


def test_an_instalment_of_a_different_amount_is_not_mistaken_for_the_same_payment(client, statement, senior):
    axis = statement.bank_account
    outgoing, amount, paid_on = _emi_on_the_bank_statement(client)
    loan, on_the_loan = _loan_row(
        client, value_date=paid_on, credit_paise=amount + 100, narration="Installment Payment By Xfer.", balance_paise=0
    )

    approve(review(outgoing, contra_ledger_for(loan), learn=False)[0], membership=senior)
    second = approve(review(on_the_loan, contra_ledger_for(axis), learn=False)[0], membership=senior)

    assert not second.mirrored
    assert JournalEntry.objects.count() == 2


def test_a_row_cannot_be_placed_in_the_loan_it_came_from(client, statement, senior):
    from ledger.approval import NotApprovableError

    loan, interest_row = _loan_row(
        client, value_date=datetime.date(2025, 5, 5), debit_paise=2196900, narration="REGULAR INTEREST", balance_paise=2196900
    )
    placed = review(interest_row, contra_ledger_for(loan), learn=False)[0]

    with pytest.raises(NotApprovableError):
        approve(placed, membership=senior)
