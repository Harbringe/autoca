"""Approval: the line between staging and the permanent record.

Everything above the ledger is editable on purpose. Everything in it is not,
and these tests attack that boundary directly -- from the application, and then
from raw SQL, because a guarantee the application enforces is a guarantee an
application bug can lose.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, review_queue
from classify.models import LedgerAccount, LedgerGroup
from classify.seeds import seed_client
from classify.treatment import Treatment
from core.db.session import firm_context
from core.models import FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from ledger.approval import (
    AlreadyPostedError,
    NotApprovableError,
    allocate_voucher_number,
    approve,
    approve_many,
    correct,
    voucher_type_for,
)
from ledger.models import Direction, JournalEntry, JournalLine, VoucherType

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def firm():
    return create_firm("Approval Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


def membership_for(firm, role):
    user = User.objects.create_user(
        email=f"{role.lower()}@example.com", password="correct-horse-battery-staple"
    )
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


@pytest.fixture
def senior(firm):
    return membership_for(firm, Role.SENIOR_CA)


@pytest.fixture
def staff(firm):
    return membership_for(firm, Role.STAFF)


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


def placed(client, fragment, target):
    """Classify one queued row and hand back its classification."""
    row = review_queue(client).filter(transaction__narration__icontains=fragment).first()
    return review(row, target)[0]


# ---------------------------------------------------------------------------
# Who may approve
# ---------------------------------------------------------------------------


def test_a_senior_ca_can_post_an_entry(client, statement, senior):
    row = placed(client, "Blinkit", ledger(client, "Office Expenses"))

    result = approve(row, membership=senior)

    assert result.entry.pk
    assert result.entry.approved_by_id == senior.user_id
    assert result.entry.approved_at is not None


def test_staff_cannot_post_an_entry(client, statement, staff):
    """A CA is personally answerable for what is filed. Hiding a button is not enforcement."""
    row = placed(client, "Blinkit", ledger(client, "Office Expenses"))

    with pytest.raises(PermissionDenied, match="journal.approve"):
        approve(row, membership=staff)

    assert JournalEntry.objects.count() == 0


def test_an_unclassified_row_cannot_be_posted(client, statement, senior):
    """Nothing unreviewed goes into the books, whoever asks."""
    unplaced = review_queue(client).filter(ledger__isnull=True).first()

    with pytest.raises(NotApprovableError, match="no ledger"):
        approve(unplaced, membership=senior)


def test_a_row_placed_in_its_own_bank_ledger_cannot_be_posted(client, statement, senior):
    """Dr Bank / Cr Bank is not an entry, however the row got there."""
    from classify.seeds import contra_ledger_for

    own = contra_ledger_for(statement.bank_account)
    row = placed(client, "Blinkit", own)

    with pytest.raises(NotApprovableError, match="bank account it came from"):
        approve(row, membership=senior)
    assert JournalEntry.objects.count() == 0


def test_a_row_in_a_proposed_ledger_cannot_be_posted_until_a_ca_accepts_it(client, statement, senior):
    from classify.models import LedgerStatus
    from classify.proposals import accept

    proposed = LedgerAccount.objects.create(
        firm_id=client.firm_id, client=client, name="Rent",
        group=LedgerGroup.INDIRECT_EXPENSE, status=LedgerStatus.PROPOSED,
    )
    row = placed(client, "Blinkit", proposed)

    with pytest.raises(NotApprovableError, match="no CA has accepted"):
        approve(row, membership=senior)
    assert JournalEntry.objects.count() == 0

    accept(proposed)
    row.refresh_from_db()
    assert approve(row, membership=senior).entry.pk


def test_the_same_transaction_cannot_be_posted_twice(client, statement, senior):
    row = placed(client, "Blinkit", ledger(client, "Office Expenses"))
    approve(row, membership=senior)

    with pytest.raises(AlreadyPostedError, match="already posted"):
        approve(row, membership=senior)


# ---------------------------------------------------------------------------
# What gets written
# ---------------------------------------------------------------------------


def test_a_payment_debits_the_expense_and_credits_the_bank(client, statement, senior):
    expenses = ledger(client, "Office Expenses")
    entry = approve(placed(client, "Blinkit", expenses), membership=senior).entry

    debit, credit = entry.lines.all()
    assert entry.voucher_type == VoucherType.PAYMENT
    assert debit.direction == Direction.DEBIT
    assert debit.ledger_account_id == expenses.pk
    assert debit.amount_paise == 530_00
    assert credit.direction == Direction.CREDIT
    assert credit.ledger_account.name == "Axis Bank A/c 4321"
    assert credit.amount_paise == 530_00


def test_a_receipt_debits_the_bank_and_credits_the_income(client, statement, senior):
    """The half everyone gets backwards."""
    income = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    entry = approve(placed(client, "102985493417", income), membership=senior).entry

    debit, credit = entry.lines.all()
    assert entry.voucher_type == VoucherType.RECEIPT
    assert debit.ledger_account.name == "Axis Bank A/c 4321"
    assert credit.ledger_account_id == income.pk


def test_a_transfer_between_the_clients_own_accounts_is_a_contra(client, statement, senior):
    other_bank = ledger(client, "HDFC Bank A/c 50100000009876", LedgerGroup.BANK)
    row = placed(client, "AXOMB20402110637", other_bank)

    assert row.is_self_transfer
    assert voucher_type_for(row) == VoucherType.CONTRA
    assert approve(row, membership=senior).entry.voucher_type == VoucherType.CONTRA


def test_the_tax_treatment_reaches_the_journal_line(client, statement, senior):
    """RCM and TDS decided at review must survive into the permanent record."""
    freight = ledger(client, "Freight Inward", LedgerGroup.DIRECT_EXPENSE)
    row = placed(
        client, "Johnson Lifts", Treatment(ledger=freight, rcm=True, tds_section="194C")
    )

    entry = approve(row, membership=senior).entry
    debit = entry.lines.get(direction=Direction.DEBIT)

    assert debit.rcm
    assert debit.tds_section == "194C"


def test_every_entry_traces_back_to_its_source_line(client, statement, senior):
    """"Where did this come from?" should be a click, not an investigation."""
    row = placed(client, "Blinkit", ledger(client, "Office Expenses"))
    entry = approve(row, membership=senior).entry

    assert entry.source_transaction_id == row.transaction_id
    assert entry.source_transaction.statement.document.sha256


def test_approval_takes_the_row_out_of_the_queue(client, statement, senior):
    before = review_queue(client).count()
    approve(placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior)

    assert review_queue(client).count() == before - 1


def test_a_batch_is_all_or_nothing(client, statement, senior):
    """One bad row must not leave the reviewer working out which half posted."""
    good = placed(client, "Blinkit", ledger(client, "Office Expenses"))
    unplaced = review_queue(client).filter(ledger__isnull=True).first()

    with pytest.raises(NotApprovableError):
        approve_many([good, unplaced], membership=senior)

    assert JournalEntry.objects.count() == 0


def test_a_clean_batch_posts_together(client, statement, senior):
    interest = review_queue(client).filter(channel="INTEREST")[:3]
    results = approve_many(list(interest), membership=senior)

    assert len(results) == 3
    assert JournalEntry.objects.count() == 3


# ---------------------------------------------------------------------------
# Voucher numbering
# ---------------------------------------------------------------------------


def test_numbers_are_contiguous_within_a_book(client, statement, senior):
    """Auditors open with this. A skipped or repeated number is a bad first minute."""
    expenses = ledger(client, "Office Expenses")
    for fragment in ("Blinkit", "SNITCH APPARELS", "Naturally Yours"):
        approve(placed(client, fragment, expenses), membership=senior)

    numbers = sorted(
        JournalEntry.objects.filter(voucher_type=VoucherType.PAYMENT).values_list(
            "entry_no", flat=True
        )
    )
    assert numbers == [1, 2, 3]


def test_each_voucher_type_has_its_own_series(client, statement, senior):
    approve(placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior)
    income = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    approve(placed(client, "102985493417", income), membership=senior)

    payment = JournalEntry.objects.get(voucher_type=VoucherType.PAYMENT)
    receipt = JournalEntry.objects.get(voucher_type=VoucherType.RECEIPT)
    assert payment.entry_no == 1
    assert receipt.entry_no == 1


def test_numbering_restarts_each_financial_year(client, statement, senior):
    """April to March, not the calendar year."""
    with firm_context(client.firm_id):
        assert allocate_voucher_number(client, 2025, VoucherType.PAYMENT) == 1
        assert allocate_voucher_number(client, 2025, VoucherType.PAYMENT) == 2
        assert allocate_voucher_number(client, 2026, VoucherType.PAYMENT) == 1


def test_an_entry_is_filed_in_the_financial_year_of_its_date(client, statement, senior):
    """31 March 2026 is FY 2025-26; 1 April 2026 is FY 2026-27."""
    entry = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry

    assert entry.entry_date == datetime.date(2026, 2, 15)
    assert entry.financial_year == 2025
    assert entry.fy_label == "2025-26"


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_a_posted_entry_cannot_be_updated(client, statement, senior):
    """Not "is not"; cannot. The grant is revoked and a trigger raises."""
    entry = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry

    with pytest.raises(DatabaseError), transaction.atomic():
        JournalEntry.objects.filter(pk=entry.pk).update(narration="tampered")


def test_a_posted_entry_cannot_be_deleted(client, statement, senior):
    entry = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry

    with pytest.raises(DatabaseError), transaction.atomic():
        JournalEntry.objects.filter(pk=entry.pk).delete()


def test_a_journal_line_cannot_be_updated(client, statement, senior):
    entry = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry

    with pytest.raises(DatabaseError), transaction.atomic():
        JournalLine.objects.filter(entry=entry).update(amount_paise=1)


def test_raw_sql_cannot_alter_an_entry_either(client, statement, senior):
    """The application is not what is holding this. The database is."""
    entry = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ledger_journal_entry SET narration = 'tampered' WHERE id = %s",
            [str(entry.pk)],
        )


def test_an_unbalanced_entry_is_refused_at_commit(client, statement, senior):
    """The double-entry invariant, held by the database rather than by hope.

    The check is deferred, so it fires at commit rather than at the offending
    statement -- an entry is written a line at a time and is legitimately
    unbalanced in between. ``SET CONSTRAINTS ALL IMMEDIATE`` brings that moment
    forward so the test can observe it.
    """
    entry = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry
    expenses = LedgerAccount.objects.get(name="Office Expenses")

    with pytest.raises(DatabaseError, match="does not balance"), transaction.atomic():
        JournalLine.objects.create(
            firm_id=client.firm_id,
            entry=entry,
            ledger_account=expenses,
            direction=Direction.DEBIT,
            amount_paise=1_00,
            signed_paise=1_00,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def test_a_correction_leaves_the_original_standing(client, statement, senior):
    """Company law expects the original to remain visible, struck through."""
    wrong = ledger(client, "Office Expenses")
    right = ledger(client, "Staff Welfare")
    original = approve(placed(client, "Blinkit", wrong), membership=senior).entry

    corrected = correct(original, membership=senior, treatment=Treatment(ledger=right))

    original.refresh_from_db()
    assert JournalEntry.objects.filter(pk=original.pk).exists()
    assert original.is_superseded
    assert original.superseded_by.pk == corrected.pk
    assert corrected.supersedes_id == original.pk


def test_a_correction_reverses_the_original_and_posts_the_new_treatment(
    client, statement, senior
):
    """The two entries together net to the corrected position, at every point."""
    wrong = ledger(client, "Office Expenses")
    right = ledger(client, "Staff Welfare")
    original = approve(placed(client, "Blinkit", wrong), membership=senior).entry

    corrected = correct(original, membership=senior, treatment=Treatment(ledger=right))

    def net(ledger_account):
        return sum(
            line.signed_paise
            for entry in (original, corrected)
            for line in entry.lines.all()
            if line.ledger_account_id == ledger_account.pk
        )

    assert net(wrong) == 0
    assert net(right) == 530_00


def test_the_correction_chain_stays_linear(client, statement, senior):
    """Two corrections of one entry would make "which is current?" ambiguous."""
    original = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry
    correct(original, membership=senior, treatment=Treatment(ledger=ledger(client, "Staff Welfare")))

    with pytest.raises(NotApprovableError, match="already been corrected"):
        correct(original, membership=senior, treatment=Treatment(ledger=ledger(client, "Rent")))


def test_staff_cannot_correct_an_entry(client, statement, senior, staff):
    original = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry

    with pytest.raises(PermissionDenied, match="journal.correct"):
        correct(original, membership=staff, treatment=Treatment(ledger=ledger(client, "Rent")))


def test_a_corrected_transaction_can_be_posted_again(client, statement, senior):
    """The superseded entry no longer counts as the live one."""
    original = approve(
        placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
    ).entry
    corrected = correct(
        original, membership=senior, treatment=Treatment(ledger=ledger(client, "Staff Welfare"))
    )

    assert not corrected.is_superseded
    assert original.is_superseded


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_another_firm_sees_no_entries(client, firm):
    """Built without the shared fixture: it holds one firm's context open."""
    other = create_firm("Other Firm")
    senior = membership_for(firm, Role.SENIOR_CA)

    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        approve(
            placed(client, "Blinkit", ledger(client, "Office Expenses")), membership=senior
        )

    with firm_context(other.pk):
        assert JournalEntry.objects.count() == 0
        assert JournalLine.objects.count() == 0


# ---------------------------------------------------------------------------
# A transfer between the client's own accounts, on both statements
# ---------------------------------------------------------------------------


def _other_account_receiving(client, amount_paise, value_date):
    """A second account whose statement shows the same transfer arriving."""
    from banking.models import BankAccount, Statement, StatementTransaction
    from classify.models import TransactionClassification
    from documents.models import Document, DocumentKind

    hdfc = BankAccount(firm_id=client.firm_id, client=client, bank_code="HDFC", ledger_name="HDFC Bank A/c 9876")
    hdfc.set_account_number("50100000009876")
    hdfc.save()
    document = Document.objects.create(
        firm_id=client.firm_id, client=client, kind=DocumentKind.BANK_STATEMENT, sha256="hdfc-test"
    )
    statement = Statement.objects.create(
        firm_id=client.firm_id, document=document, bank_account=hdfc,
        period_start=value_date, period_end=value_date,
        opening_balance_paise=0, closing_balance_paise=amount_paise,
        total_debit_paise=0, total_credit_paise=amount_paise, transaction_count=1,
    )
    txn = StatementTransaction.objects.create(
        firm_id=client.firm_id, statement=statement, bank_account=hdfc, row_number=1,
        value_date=value_date, narration="NEFT/AXIS/RAMESH GOPAL DESHMUKH/Self",
        credit_paise=amount_paise, balance_paise=amount_paise, dedupe_hash="hdfc-row-1",
    )
    row = TransactionClassification.objects.create(firm_id=client.firm_id, transaction=txn, is_self_transfer=True)
    return hdfc, row


def test_a_transfer_seen_on_both_statements_is_posted_once(client, statement, senior):
    from classify.seeds import contra_ledger_for
    from ledger.reconciliation import ledger_balance

    axis = statement.bank_account
    outgoing = review_queue(client).filter(transaction__narration__icontains="AXOMB20402110637").first()
    amount, sent_on = outgoing.transaction.amount_paise, outgoing.transaction.value_date
    hdfc, incoming = _other_account_receiving(client, amount, sent_on + datetime.timedelta(days=1))

    first = approve(review(outgoing, contra_ledger_for(hdfc), learn=False)[0], membership=senior)
    second = approve(review(incoming, contra_ledger_for(axis), learn=False)[0], membership=senior)

    assert first.entry.voucher_type == VoucherType.CONTRA and not first.mirrored
    assert second.mirrored and second.entry.pk == first.entry.pk
    assert JournalEntry.objects.filter(voucher_type=VoucherType.CONTRA).count() == 1
    assert not review_queue(client).filter(pk=incoming.pk).exists()
    assert ledger_balance(hdfc, sent_on + datetime.timedelta(days=2)) == amount

    with pytest.raises(AlreadyPostedError):
        approve(incoming, membership=senior)


def test_a_similar_transfer_outside_the_window_is_not_mistaken_for_the_same_one(client, statement, senior):
    from classify.seeds import contra_ledger_for

    axis = statement.bank_account
    outgoing = review_queue(client).filter(transaction__narration__icontains="AXOMB20402110637").first()
    amount, sent_on = outgoing.transaction.amount_paise, outgoing.transaction.value_date
    hdfc, incoming = _other_account_receiving(client, amount, sent_on + datetime.timedelta(days=30))

    approve(review(outgoing, contra_ledger_for(hdfc), learn=False)[0], membership=senior)
    second = approve(review(incoming, contra_ledger_for(axis), learn=False)[0], membership=senior)

    assert not second.mirrored
    assert JournalEntry.objects.filter(voucher_type=VoucherType.CONTRA).count() == 2
