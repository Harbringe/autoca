"""Upload bytes in, proved rows out.

The only entry point business code should use is :func:`ingest_statement`. It
runs the whole path in one place so that the ordering of its steps is a property
of the system rather than of whoever wired it up:

    bytes -> text layer -> detect bank -> parse and prove -> store -> persist

Two of those steps are refusals rather than transformations. A scan is rejected
instead of being parsed to zero rows, and a statement whose arithmetic does not
close raises before anything is written. Nothing partially-parsed reaches the
database, because the alternative is a client's books quietly missing a page.

The caller supplies the tenant context. This module never opens one: a function
that sets its own firm context can be called with the wrong firm and will
happily comply, whereas one that inherits the ambient context cannot.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.db import transaction

from banking.models import BankAccount, Statement, StatementTransaction
from banking.parsers import ParsedStatement, parse_statement
from core.models import Client
from integrations.registry import get_pdf, get_storage


@dataclass(frozen=True)
class IngestResult:
    statement: Statement
    parsed: ParsedStatement
    rows_created: int
    rows_already_present: int
    #: False when this exact file had been ingested before. The caller gets the
    #: original statement back rather than a duplicate or an exception, because
    #: re-uploading the same file is a user action, not a user error.
    is_new: bool

    @property
    def bank_account(self) -> BankAccount:
        return self.statement.bank_account


def ingest_statement(
    *,
    client: Client,
    data: bytes,
    filename: str = "",
    store_original: bool = True,
) -> IngestResult:
    """Parse ``data`` as a bank statement for ``client`` and persist its rows."""
    digest = hashlib.sha256(data).hexdigest()
    parsed = parse_statement(get_pdf().extract(data))

    account = _account_for(client, parsed)

    existing = Statement.objects.filter(
        firm_id=client.firm_id, bank_account=account, source_sha256=digest
    ).first()
    if existing is not None:
        return IngestResult(
            statement=existing,
            parsed=parsed,
            rows_created=0,
            rows_already_present=existing.transaction_count,
            is_new=False,
        )

    storage_key = ""
    if store_original:
        storage_key = _store_original(client, digest, filename, data)

    with transaction.atomic():
        statement = Statement.objects.create(
            firm_id=client.firm_id,
            bank_account=account,
            source_filename=filename[:255],
            source_sha256=digest,
            storage_key=storage_key,
            period_start=parsed.period_start,
            period_end=parsed.period_end,
            opening_balance=parsed.opening_balance,
            closing_balance=parsed.closing_balance,
            total_debit=parsed.total_debit,
            total_credit=parsed.total_credit,
            transaction_count=len(parsed),
            parser=parsed.bank_code,
        )
        created, skipped = _persist_rows(statement, account, parsed)

    return IngestResult(
        statement=statement,
        parsed=parsed,
        rows_created=created,
        rows_already_present=skipped,
        is_new=True,
    )


def _account_for(client: Client, parsed: ParsedStatement) -> BankAccount:
    """Find or open the account this statement belongs to.

    Matching is on the account number the statement itself prints. A firm does
    not pre-register accounts before uploading -- the statement is the source of
    truth for which account it is, and asking a user to pick from a dropdown
    just adds a way to file a statement against the wrong account.
    """
    account, created = BankAccount.objects.get_or_create(
        firm_id=client.firm_id,
        client=client,
        bank_code=parsed.bank_code,
        account_number=parsed.account_number,
        defaults={"ifsc": parsed.ifsc, "account_holder": parsed.account_holder},
    )
    if not created:
        latest = {"ifsc": parsed.ifsc, "account_holder": parsed.account_holder}
        changed = [f for f, value in latest.items() if value and getattr(account, f) != value]
        for field in changed:
            setattr(account, field, latest[field])
        if changed:
            account.save(update_fields=changed)
    return account


def _store_original(client: Client, digest: str, filename: str, data: bytes) -> str:
    """Keep the source file. The parse is derived; the PDF is the evidence.

    Keyed by content hash under the firm's storage prefix, so the same file
    uploaded twice occupies one object and no key can be built that points at
    another firm's prefix.
    """
    storage = get_storage()
    key = storage.tenant_key(
        client.firm_id, "clients", str(client.id), "statements", f"{digest}.pdf"
    )
    storage.put(key, data, content_type="application/pdf")
    return key


def _persist_rows(
    statement: Statement, account: BankAccount, parsed: ParsedStatement
) -> tuple[int, int]:
    """Write the rows, skipping any this account has already seen.

    Overlapping statement periods are normal, so a collision on ``dedupe_hash``
    is an expected outcome and not an error.
    """
    hashes = {}
    rows = []
    for txn in parsed.transactions:
        digest = StatementTransaction.compute_dedupe_hash(
            account_number=parsed.account_number,
            value_date=txn.date,
            narration=txn.narration,
            debit=txn.debit,
            credit=txn.credit,
            balance=txn.balance,
        )
        hashes[digest] = txn
        rows.append(
            StatementTransaction(
                firm_id=statement.firm_id,
                statement=statement,
                bank_account=account,
                row_number=txn.row_number,
                value_date=txn.date,
                narration=txn.narration,
                cheque_number=txn.cheque_number,
                debit=txn.debit,
                credit=txn.credit,
                balance=txn.balance,
                branch_code=txn.branch_code,
                dedupe_hash=digest,
            )
        )

    already = set(
        StatementTransaction.objects.filter(
            firm_id=statement.firm_id, bank_account=account, dedupe_hash__in=hashes
        ).values_list("dedupe_hash", flat=True)
    )
    fresh = [row for row in rows if row.dedupe_hash not in already]
    StatementTransaction.objects.bulk_create(fresh)
    return len(fresh), len(rows) - len(fresh)
