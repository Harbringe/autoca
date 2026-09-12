"""Row factories for the cross-tenant isolation suite.

Every firm-scoped model needs an entry in ``FACTORIES``. This is not
boilerplate for its own sake -- ``test_rls_isolation.py`` fails the build if a
firm-scoped model has no factory, which is what makes the isolation suite grow
along with the schema instead of quietly falling behind it.

Adding a model to the system therefore forces you to say how to create one, and
the suite immediately starts attacking it from the wrong tenant.
"""

from __future__ import annotations

import datetime
import uuid

from django.utils import timezone as django_timezone

from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import (
    ClassificationRule,
    LedgerAccount,
    LedgerGroup,
    TransactionClassification,
    Vendor,
)
from core.models import AuditLog, Client, Firm, FirmMembership, Role, User
from documents.models import Document, DocumentKind
from ledger.models import Direction, JournalEntry, JournalLine, VoucherSequence, VoucherType


def _client(firm, **kw):
    return Client.objects.create(
        firm=firm,
        name=kw.get("name", f"Client {uuid.uuid4().hex[:8]}"),
        fy_start=kw.get("fy_start", datetime.date(2026, 4, 1)),
    )


def _membership(firm, **kw):
    user = kw.get("user") or User.objects.create_user(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password="correct-horse-battery"
    )
    return FirmMembership.objects.create(firm=firm, user=user, role=kw.get("role", Role.STAFF))


def _audit(firm, **kw):
    return AuditLog.objects.create(
        firm=firm,
        user=kw.get("user"),
        method="POST",
        path="/test/",
        status_code=200,
        request_id=uuid.uuid4().hex,
    )


def _bank_account(firm, **kw):
    account = BankAccount(
        firm=firm,
        client=kw.get("client") or _client(firm),
        bank_code=kw.get("bank_code", "AXIS"),
        ifsc=kw.get("ifsc", "UTIB0000318"),
    )
    account.set_account_number(str(kw.get("account_number", uuid.uuid4().int % 10**15)))
    account.set_account_holder(kw.get("account_holder", "RAMESH GOPAL DESHMUKH"))
    account.save()
    return account


def _document(firm, **kw):
    return Document.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        kind=kw.get("kind", DocumentKind.BANK_STATEMENT),
        original_filename="statement.pdf",
        sha256=kw.get("sha256", uuid.uuid4().hex * 2),
    )


def _statement(firm, **kw):
    account = kw.get("bank_account") or _bank_account(firm)
    return Statement.objects.create(
        firm=firm,
        document=kw.get("document") or _document(firm, client=account.client),
        bank_account=account,
        period_start=datetime.date(2025, 4, 1),
        period_end=datetime.date(2026, 3, 31),
        opening_balance_paise=100_000,
        closing_balance_paise=90_000,
        total_debit_paise=10_000,
        total_credit_paise=0,
        transaction_count=1,
        parser="AXIS",
    )


def _statement_transaction(firm, **kw):
    statement = kw.get("statement") or _statement(firm)
    return StatementTransaction.objects.create(
        firm=firm,
        statement=statement,
        bank_account=statement.bank_account,
        row_number=kw.get("row_number", 1),
        value_date=datetime.date(2025, 4, 13),
        narration="Sweep/VO000000087559330/19000014841287",
        debit_paise=10_000,
        credit_paise=0,
        balance_paise=90_000,
        dedupe_hash=uuid.uuid4().hex * 2,
    )


def _ledger_account(firm, **kw):
    return LedgerAccount.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        name=kw.get("name", f"Ledger {uuid.uuid4().hex[:8]}"),
        group=kw.get("group", LedgerGroup.INDIRECT_EXPENSE),
    )


def _vendor(firm, **kw):
    return Vendor.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        canonical_name=kw.get("canonical_name", f"Vendor {uuid.uuid4().hex[:8]}"),
    )


def _classification_rule(firm, **kw):
    ledger = kw.get("ledger") or _ledger_account(firm)
    return ClassificationRule.objects.create(
        firm=firm,
        client=ledger.client,
        ledger=ledger,
        pattern=kw.get("pattern", uuid.uuid4().hex[:10].upper()),
    )


def _transaction_classification(firm, **kw):
    txn = kw.get("transaction") or _statement_transaction(firm)
    return TransactionClassification.objects.create(
        firm=firm,
        transaction=txn,
        counterparty="ACME TRADERS",
        channel="UPI",
    )


def _voucher_sequence(firm, **kw):
    return VoucherSequence.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        financial_year=kw.get("financial_year", 2025),
        voucher_type=kw.get("voucher_type", VoucherType.PAYMENT),
    )


def _journal_entry(firm, **kw):
    txn = kw.get("transaction") or _statement_transaction(firm)
    return JournalEntry.objects.create(
        firm=firm,
        client=txn.bank_account.client,
        entry_no=kw.get("entry_no", 1),
        financial_year=2025,
        entry_date=datetime.date(2025, 4, 13),
        voucher_type=VoucherType.PAYMENT,
        narration="Sweep/VO000000087559330/19000014841287",
        source_transaction=txn,
        approved_at=django_timezone.now(),
    )


def _journal_line(firm, **kw):
    """A balanced pair, because a lone line fails the deferred balance trigger."""
    entry = kw.get("entry") or _journal_entry(firm)
    ledger = kw.get("ledger_account") or _ledger_account(firm, client=entry.client)
    debit = JournalLine.build(
        entry=entry, ledger_account=ledger, direction=Direction.DEBIT, amount_paise=10_000
    )
    credit = JournalLine.build(
        entry=entry, ledger_account=ledger, direction=Direction.CREDIT, amount_paise=10_000
    )
    JournalLine.objects.bulk_create([debit, credit])
    return debit


#: model -> callable(firm, **kwargs) -> instance
FACTORIES = {
    Client: _client,
    FirmMembership: _membership,
    AuditLog: _audit,
    Document: _document,
    BankAccount: _bank_account,
    Statement: _statement,
    StatementTransaction: _statement_transaction,
    LedgerAccount: _ledger_account,
    Vendor: _vendor,
    ClassificationRule: _classification_rule,
    TransactionClassification: _transaction_classification,
    VoucherSequence: _voucher_sequence,
    JournalEntry: _journal_entry,
    JournalLine: _journal_line,
}

#: Firm is firm-scoped by primary key rather than by a firm_id column, so it is
#: handled separately by the suite rather than through FACTORIES.
TENANT_ROOT = Firm
