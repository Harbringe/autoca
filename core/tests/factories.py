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
import decimal
import uuid

from banking.models import BankAccount, Statement, StatementTransaction
from core.models import AuditLog, Client, Firm, FirmMembership, Role, User


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
    return BankAccount.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        bank_code=kw.get("bank_code", "AXIS"),
        account_number=kw.get("account_number", uuid.uuid4().int % 10**15),
        ifsc=kw.get("ifsc", "UTIB0000318"),
    )


def _statement(firm, **kw):
    account = kw.get("bank_account") or _bank_account(firm)
    return Statement.objects.create(
        firm=firm,
        bank_account=account,
        source_filename="statement.pdf",
        source_sha256=uuid.uuid4().hex * 2,
        period_start=datetime.date(2025, 4, 1),
        period_end=datetime.date(2026, 3, 31),
        opening_balance=decimal.Decimal("1000.00"),
        closing_balance=decimal.Decimal("900.00"),
        total_debit=decimal.Decimal("100.00"),
        total_credit=decimal.Decimal("0.00"),
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
        debit=decimal.Decimal("100.00"),
        credit=decimal.Decimal("0.00"),
        balance=decimal.Decimal("900.00"),
        dedupe_hash=uuid.uuid4().hex * 2,
    )


#: model -> callable(firm, **kwargs) -> instance
FACTORIES = {
    Client: _client,
    FirmMembership: _membership,
    AuditLog: _audit,
    BankAccount: _bank_account,
    Statement: _statement,
    StatementTransaction: _statement_transaction,
}

#: Firm is firm-scoped by primary key rather than by a firm_id column, so it is
#: handled separately by the suite rather than through FACTORIES.
TENANT_ROOT = Firm
