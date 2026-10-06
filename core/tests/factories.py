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
    Party,
    PartyAlias,
    PartyBankAccount,
    TransactionClassification,
)
from classify.narration import normalise
from core.models import AuditLog, Client, ClientAssignment, Firm, FirmMembership, Job, Role, User
from documents.models import Document, DocumentKind
from gst.models import (
    DecisionKind,
    Gstr2bInvoice,
    GstRegistration,
    ReconDecision,
    ReconMatch,
    ReconRun,
    RegisterInvoice,
)
from ledger.models import (
    AllocationKind,
    Bill,
    BillAllocation,
    BillKind,
    BooksAction,
    BooksEvent,
    ChangeAction,
    Direction,
    EntryChange,
    InvoiceReading,
    JournalEntry,
    JournalLine,
    LedgerImportRun,
    LedgerOpening,
    VoucherSequence,
    VoucherType,
)
from teams.models import ActivityEvent, ActivityKind, Invite, TeamEvent, TeamEventKind


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


def _job(firm, **kw):
    return Job.objects.create(
        firm=firm,
        kind=kw.get("kind", "statement.ingest"),
        idempotency_key=kw.get("idempotency_key", uuid.uuid4().hex),
    )


def _bank_account(firm, **kw):
    account = BankAccount(
        firm=firm,
        client=kw.get("client") or _client(firm),
        bank_code=kw.get("bank_code", "AXIS"),
        ifsc=kw.get("ifsc", "UTIB0000001"),
    )
    account.set_account_number(str(kw.get("account_number", uuid.uuid4().int % 10**15)))
    account.set_account_holder(kw.get("account_holder", "ARJUN PRATAP NAIR"))
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
        narration="Sweep/VO000000012345678/19000000000001",
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


def _party(firm, **kw):
    return Party.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        canonical_name=kw.get("canonical_name", f"Party {uuid.uuid4().hex[:8]}"),
    )


def _party_alias(firm, **kw):
    party = kw.get("party") or _party(firm)
    name = kw.get("alias_display", f"Alias {uuid.uuid4().hex[:8]}")
    return PartyAlias.objects.create(
        firm=firm,
        client=party.client,
        party=party,
        alias_normalised=normalise(name),
        alias_display=name,
    )


def _party_bank_account(firm, **kw):
    party = kw.get("party") or _party(firm)
    return PartyBankAccount.objects.create(
        firm=firm,
        client=party.client,
        party=party,
        account_hash=kw.get("account_hash", uuid.uuid4().hex),
        last4=kw.get("last4", "0001"),
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
        narration="Sweep/VO000000012345678/19000000000001",
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


def _books_event(firm, **kw):
    return BooksEvent.objects.create(
        firm=firm, client=kw.get("client") or _client(firm), action=BooksAction.REQUESTED
    )


def _entry_change(firm, **kw):
    return EntryChange.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        entry_id=uuid.uuid4(),
        voucher_type=VoucherType.PAYMENT,
        entry_no=1,
        entry_date=datetime.date(2025, 4, 13),
        action=ChangeAction.REMOVED,
        before={},
    )


def _client_assignment(firm, **kw):
    return ClientAssignment.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        membership=kw.get("membership") or _membership(firm),
    )


def _invite(firm, **kw):
    return Invite.objects.create(
        firm=firm,
        email=f"{uuid.uuid4().hex[:10]}@example.com",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=django_timezone.now() + datetime.timedelta(days=7),
    )


def _activity_event(firm, **kw):
    return ActivityEvent.objects.create(
        firm=firm, user_id=uuid.uuid4(), kind=ActivityKind.ROW_PLACED, quantity=1
    )


def _team_event(firm, **kw):
    return TeamEvent.objects.create(firm=firm, kind=TeamEventKind.ASSIGNED, detail={})



def _gst_registration(firm, **kw):
    reg = GstRegistration(
        firm=firm, client=kw.get("client") or _client(firm), state_code=kw.get("state_code", "27")
    )
    reg.set_gstin(kw.get("gstin", "27AAAPL1234C1Z5"))
    reg.save()
    return reg


def _gst_run(firm, **kw):
    registration = kw.get("registration") or _gst_registration(firm)
    return ReconRun.objects.create(
        firm=firm,
        client=registration.client,
        registration=registration,
        period_start=kw.get("period_start", datetime.date(2026, 8, 1)),
    )


def _gst_row(model, firm, **kw):
    run = kw.get("run") or _gst_run(firm)
    row = model(
        firm=firm, run=run, invoice_no=kw.get("invoice_no", f"INV-{uuid.uuid4().hex[:6]}"),
        invoice_date=datetime.date(2026, 8, 10), cgst_paise=90000, sgst_paise=90000,
    )
    row.set_gstin(kw.get("gstin", "27AAAPL1234C1Z5"))
    row.save()
    return row


def _gst_register_invoice(firm, **kw):
    return _gst_row(RegisterInvoice, firm, **kw)


def _gst_portal_invoice(firm, **kw):
    return _gst_row(Gstr2bInvoice, firm, **kw)


def _gst_match(firm, **kw):
    run = kw.get("run") or _gst_run(firm)
    return ReconMatch.objects.create(firm=firm, run=run, kind="missing_in_2b", itc_status="not_eligible")


def _gst_decision(firm, **kw):
    return ReconDecision.objects.create(
        firm=firm, run=kw.get("run") or _gst_run(firm), kind=DecisionKind.NOTE, note="checked"
    )


def _ledger_import_run(firm, **kw):
    return LedgerImportRun.objects.create(
        firm=firm,
        client=kw.get("client") or _client(firm),
        financial_year=2025,
        file_sha256=uuid.uuid4().hex * 2,
        source_format="xml",
        chart_stamp="x",
        expires_at=django_timezone.now() + datetime.timedelta(days=7),
    )


def _ledger_opening(firm, **kw):
    client = kw.get("client") or _client(firm)
    return LedgerOpening.objects.create(
        firm=firm,
        client=client,
        ledger=kw.get("ledger") or _ledger_account(firm, client=client),
        financial_year=2025,
        signed_paise=150_000,
    )


def _bill(firm, **kw):
    client = kw.get("client") or _client(firm)
    return Bill.objects.create(
        firm=firm,
        client=client,
        party=kw.get("party") or _party(firm, client=client),
        kind=BillKind.PURCHASE,
        direction=Direction.CREDIT,
        reference=f"INV-{uuid.uuid4().hex[:8]}",
        bill_date=datetime.date(2025, 4, 13),
        booked_on=datetime.date(2025, 4, 13),
        financial_year=2025,
        taxable_paise=100_000,
        total_paise=100_000,
        invoice_key=uuid.uuid4().hex * 2,
    )


def _invoice_reading(firm, **kw):
    client = kw.get("client") or _client(firm)
    return InvoiceReading.objects.create(
        firm=firm, client=client, document=kw.get("document") or _document(firm, client=client), kind=BillKind.PURCHASE
    )


def _bill_allocation(firm, **kw):
    """A payment line on the party's own ledger, settling the bill in full."""
    bill = kw.get("bill") or _bill(firm)
    party_ledger = LedgerAccount.objects.create(
        firm=firm, client=bill.client, name=f"Party {uuid.uuid4().hex[:8]}", group=LedgerGroup.CREDITOR
    )
    bill.party.ledger = party_ledger
    bill.party.save(update_fields=["ledger"])
    bank = _ledger_account(firm, client=bill.client, group=LedgerGroup.BANK)
    entry = JournalEntry.objects.create(
        firm=firm,
        client=bill.client,
        entry_no=1,
        financial_year=2025,
        entry_date=datetime.date(2025, 4, 20),
        voucher_type=VoucherType.PAYMENT,
        narration="Paid against the bill",
        approved_at=django_timezone.now(),
    )
    debit = JournalLine.build(
        entry=entry, ledger_account=party_ledger, party=bill.party, direction=Direction.DEBIT, amount_paise=100_000
    )
    credit = JournalLine.build(entry=entry, ledger_account=bank, direction=Direction.CREDIT, amount_paise=100_000)
    JournalLine.objects.bulk_create([debit, credit])
    return BillAllocation.objects.create(
        firm=firm, client=bill.client, line=debit, bill=bill, kind=AllocationKind.AGAINST_BILL, amount_paise=100_000
    )


#: model -> callable(firm, **kwargs) -> instance
FACTORIES = {
    Client: _client,
    FirmMembership: _membership,
    ClientAssignment: _client_assignment,
    Invite: _invite,
    ActivityEvent: _activity_event,
    TeamEvent: _team_event,
    AuditLog: _audit,
    Job: _job,
    Document: _document,
    GstRegistration: _gst_registration,
    ReconRun: _gst_run,
    RegisterInvoice: _gst_register_invoice,
    Gstr2bInvoice: _gst_portal_invoice,
    ReconMatch: _gst_match,
    ReconDecision: _gst_decision,
    BankAccount: _bank_account,
    Statement: _statement,
    StatementTransaction: _statement_transaction,
    LedgerAccount: _ledger_account,
    Party: _party,
    PartyAlias: _party_alias,
    PartyBankAccount: _party_bank_account,
    ClassificationRule: _classification_rule,
    TransactionClassification: _transaction_classification,
    VoucherSequence: _voucher_sequence,
    JournalEntry: _journal_entry,
    JournalLine: _journal_line,
    BooksEvent: _books_event,
    EntryChange: _entry_change,
    LedgerImportRun: _ledger_import_run,
    LedgerOpening: _ledger_opening,
    Bill: _bill,
    BillAllocation: _bill_allocation,
    InvoiceReading: _invoice_reading,
}

#: Firm is firm-scoped by primary key rather than by a firm_id column, so it is
#: handled separately by the suite rather than through FACTORIES.
TENANT_ROOT = Firm
