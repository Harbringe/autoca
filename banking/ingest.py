"""Upload bytes in, proved rows out.

The only entry point business code should use is :func:`ingest_statement`. It
runs the whole path in one place so the ordering of its steps is a property of
the system rather than of whoever wired it up:

    bytes -> document registry -> text layer -> detect bank
          -> parse and prove -> continuity check -> persist

Three of those steps are refusals rather than transformations. A scan is
rejected instead of being parsed to zero rows; a statement whose arithmetic does
not close raises before anything is written; and a statement that does not
continue from the last one for that account is a blocking warning, not something
quietly absorbed. Nothing partially-parsed reaches the database, because the
alternative is a client's books silently missing a page.

The caller supplies the tenant context. This module never opens one: a function
that sets its own firm context can be called with the wrong firm and will
happily comply, whereas one that inherits the ambient context cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from banking.models import BankAccount, Statement, StatementTransaction
from banking.parsers import ParsedStatement, detect_parser
from core.models import Client
from core.money import format_inr
from documents.models import Document, DocumentKind, DocumentStatus, PipelineTier
from integrations.registry import get_pdf, get_storage


class StatementContinuityError(RuntimeError):
    """This statement does not carry on from the last one for the account.

    A gap means a missing statement period. Absorbing it silently would leave
    the books balanced against a bank balance nobody reconciled, which is the
    error month-end review exists to catch and which is far cheaper to catch
    here.
    """


@dataclass(frozen=True)
class IngestResult:
    statement: Statement
    document: Document
    #: None when this file had already been ingested -- it is not re-parsed, so
    #: there is no fresh parse to hand back.
    parsed: ParsedStatement | None
    rows_created: int
    rows_already_present: int
    #: False when this exact file had been ingested before. The caller gets the
    #: original statement back rather than a duplicate or an exception, because
    #: re-uploading the same file is a user action, not a user error.
    is_new: bool
    #: True when this is the first statement for the account and its opening
    #: balance still needs a person to confirm it. A client onboarding mid-year
    #: has history this system never saw.
    needs_opening_confirmation: bool = False

    @property
    def bank_account(self) -> BankAccount:
        return self.statement.bank_account


class StatementElsewhereError(RuntimeError):
    """The file was uploaded before, for a different client."""


def ingest_statement(
    *,
    client: Client,
    data: bytes,
    filename: str = "",
    uploaded_by=None,
    store_original: bool = True,
    allow_gap: bool = False,
) -> IngestResult:
    """Parse ``data`` as a bank statement for ``client`` and persist its rows."""
    digest = Document.digest(data)

    existing = Document.objects.filter(firm_id=client.firm_id, sha256=digest).first()
    if existing is not None and hasattr(existing, "statement"):
        statement = existing.statement
        if statement.bank_account.client_id != client.pk:
            # The same file under a second client is a mistake, not a repeat. Saying "already
            # imported" would hide it -- and hand back a statement from books the uploader may
            # not be allowed to see -- so it is refused, without naming the other client.
            raise StatementElsewhereError(
                "This exact file is already on file for another client of the firm. Check you have "
                "the right client open, or the right file."
            )
        return IngestResult(
            statement=statement,
            document=existing,
            parsed=None,
            rows_created=0,
            rows_already_present=statement.transaction_count,
            is_new=False,
        )

    document = get_pdf().extract(data)
    parser = detect_parser(document)
    parsed = parser.parse(document)

    account = _account_for(client, parsed)
    _check_continuity(account, parsed, allow_gap=allow_gap)

    storage_key = ""
    if store_original:
        storage_key = _store_original(client, digest, data)

    with transaction.atomic():
        # ``existing`` here means the file was registered by an earlier attempt
        # that failed before producing a statement. Reuse the row rather than
        # colliding with its unique hash, and bring its status up to date.
        record = existing or Document(
            firm_id=client.firm_id,
            client=client,
            kind=DocumentKind.BANK_STATEMENT,
            sha256=digest,
            uploaded_by=uploaded_by,
        )
        record.original_filename = filename[:255] or record.original_filename
        record.storage_key = storage_key or record.storage_key
        record.byte_size = len(data)
        record.page_count = document.page_count
        record.pipeline_tier = PipelineTier.TEXT_LAYER
        record.status = DocumentStatus.PARSED
        record.failure_reason = ""
        record.save()

        statement = Statement.objects.create(
            firm_id=client.firm_id,
            document=record,
            bank_account=account,
            period_start=parsed.period_start,
            period_end=parsed.period_end,
            opening_balance_paise=parsed.opening_balance_paise,
            closing_balance_paise=parsed.closing_balance_paise,
            total_debit_paise=parsed.total_debit_paise,
            total_credit_paise=parsed.total_credit_paise,
            transaction_count=len(parsed),
            parser=parsed.bank_code,
            parser_version=parser.version,
        )
        created, skipped = _persist_rows(statement, account, parsed)

    return IngestResult(
        statement=statement,
        document=record,
        parsed=parsed,
        rows_created=created,
        rows_already_present=skipped,
        is_new=True,
        needs_opening_confirmation=not account.has_opening_balance,
    )


def confirm_opening_balance(account: BankAccount, *, balance_paise: int, as_of) -> BankAccount:
    """Record the balance a client's books actually started from.

    Pre-filled from the first statement's own opening line, but confirmed by a
    person rather than assumed, because the statement's opening line is only the
    truth if the client has been with the firm since that date. A client
    onboarding in October has six months this system never saw, and starting
    them at the October statement's opening figure quietly misstates every
    balance from then on.
    """
    account.opening_balance_paise = int(balance_paise)
    account.opening_as_of = as_of
    account.save(update_fields=["opening_balance_paise", "opening_as_of"])
    return account


def _check_continuity(account: BankAccount, parsed: ParsedStatement, *, allow_gap: bool) -> None:
    """The statement must start where the previous one for this account ended.

    Within a statement the balance chain proves no row was lost. Across
    statements nothing proves it, and a missing month is exactly as damaging --
    which is why the architecture calls for this to be a blocking warning rather
    than something absorbed.
    """
    previous = (
        Statement.objects.filter(
            firm_id=account.firm_id, bank_account=account, period_end__lte=parsed.period_start
        )
        .order_by("-period_end")
        .first()
    )
    if previous is None or allow_gap:
        return
    if previous.closing_balance_paise == parsed.opening_balance_paise:
        return

    raise StatementContinuityError(
        f"This statement opens at {format_inr(parsed.opening_balance_paise)}, but the "
        f"last statement for {account} closed at "
        f"{format_inr(previous.closing_balance_paise)} on "
        f"{previous.period_end:%d-%m-%Y}. A statement period is missing between the "
        f"two. Upload the missing statement first, or import this one anyway to record "
        f"the gap deliberately."
    )


def _account_for(client: Client, parsed: ParsedStatement) -> BankAccount:
    """Find or open the account this statement belongs to.

    Matching is on the account number the statement itself prints, via its blind
    index -- the number is encrypted, so this is the only way to find the row. A
    firm does not pre-register accounts before uploading: the statement is the
    source of truth for which account it is, and a dropdown just adds a way to
    file a statement against the wrong one.
    """
    lookup = BankAccount.lookup_hash(parsed.account_number, client.firm_id)
    account = BankAccount.objects.filter(
        firm_id=client.firm_id,
        client=client,
        bank_code=parsed.bank_code,
        account_number_hash=lookup,
    ).first()

    if account is None:
        account = BankAccount(
            firm_id=client.firm_id,
            client=client,
            bank_code=parsed.bank_code,
            ifsc=parsed.ifsc,
        )
        account.set_account_number(parsed.account_number)
        account.set_account_holder(parsed.account_holder)
        account.save()
        return account

    changed = []
    if parsed.ifsc and account.ifsc != parsed.ifsc:
        account.ifsc = parsed.ifsc
        changed.append("ifsc")
    if parsed.account_holder and account.account_holder != parsed.account_holder:
        account.set_account_holder(parsed.account_holder)
        changed.append("account_holder_enc")
    if changed:
        account.save(update_fields=changed)
    return account


def _store_original(client: Client, digest: str, data: bytes) -> str:
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
    rows = []
    digests = set()
    for txn in parsed.transactions:
        digest = StatementTransaction.compute_dedupe_hash(
            account_hash=account.account_number_hash,
            value_date=txn.date,
            narration=txn.narration,
            debit_paise=txn.debit_paise,
            credit_paise=txn.credit_paise,
            balance_paise=txn.balance_paise,
        )
        digests.add(digest)
        rows.append(
            StatementTransaction(
                firm_id=statement.firm_id,
                statement=statement,
                bank_account=account,
                row_number=txn.row_number,
                value_date=txn.date,
                narration=txn.narration,
                cheque_number=txn.cheque_number,
                debit_paise=txn.debit_paise,
                credit_paise=txn.credit_paise,
                balance_paise=txn.balance_paise,
                branch_code=txn.branch_code,
                dedupe_hash=digest,
            )
        )

    already = set(
        StatementTransaction.objects.filter(
            firm_id=statement.firm_id, bank_account=account, dedupe_hash__in=digests
        ).values_list("dedupe_hash", flat=True)
    )
    fresh = [row for row in rows if row.dedupe_hash not in already]
    StatementTransaction.objects.bulk_create(fresh)
    return len(fresh), len(rows) - len(fresh)
