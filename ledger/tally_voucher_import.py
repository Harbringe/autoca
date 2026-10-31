"""Bringing a client's Tally vouchers in, exactly as Tally had them.

Same shape as ``ledger.tally_import``: staging is mutable and the books are not. ``stage_vouchers`` reads the file, plans
every voucher, and writes one :class:`~ledger.models.LedgerImportRun` -- a preview, nothing else. ``confirm_vouchers`` writes
each voucher in its own transaction, and ``undo_run`` takes a whole run back out. Nothing here logs a name; the run records
counts and who.

The lines of a voucher are never rebuilt (see ``ledger.tally_plan``): the books must equal Tally's. No file is kept, so a
staged row carries everything its confirm needs.

A bank voucher also becomes a row on that bank account's statement. The statement is a placeholder (a ``Document`` of kind
Tally export) whose balances are worked out from the rows, so it proves by construction; each row is placed by a person's
decision -- the accountant's, in Tally -- which is what the assistant later learns from.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import logging
import os
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone

from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import (
    CRYPTO_PURPOSE,
    ClassificationMethod,
    ClassificationRule,
    LedgerAccount,
    LedgerGroup,
    Party,
    PartyRole,
    TransactionClassification,
)
from classify.treatment import ReviewBand
from core.crypto import blind_index
from core.fy import financial_year
from core.identity import invoice_key, normalise_gstin, supplier_identity
from documents.models import Document, DocumentKind, DocumentStatus, PipelineTier
from integrations.registry import get_storage
from integrations.storage.base import StorageAdapter
from ledger import editing
from ledger.approval import allocate_voucher_number
from ledger.billing import BillingError, allocate, line_unallocated, open_amount
from ledger.models import (
    AllocationKind,
    Bill,
    BillAllocation,
    BillKind,
    ChangeAction,
    Direction,
    EntryMarker,
    ImportKind,
    ImportStatus,
    JournalEntry,
    JournalLine,
    LedgerImportRun,
    StockEntry,
    StockEntryKind,
    TallyVoucher,
    VoucherType,
)
from ledger.tally_bankreport import parse_bank_report
from ledger.tally_import import (
    TallyImportError,
    TallyOverlapError,
    TallyRunStaleError,
    _require_rights,
    chart_stamp,
)
from ledger.tally_learning import learn_rules
from ledger.tally_parse import normal_name
from ledger.tally_plan import STANDARD_TYPES, Facts, Planned, plan_voucher
from ledger.tally_vouchers import ParsedVoucher, VoucherLine, parse_vouchers

logger = logging.getLogger("autoca.tally")

_BANKS = (LedgerGroup.BANK, LedgerGroup.BANK_OD)

#: Which way stock moves for the vouchers that carry items: goods in on a purchase or a sales return, out on a sale or a purchase return.
_STOCK_DIRECTION = {
    VoucherType.PURCHASE: "IN",
    VoucherType.CREDIT_NOTE: "IN",
    VoucherType.SALES: "OUT",
    VoucherType.DEBIT_NOTE: "OUT",
}


def _facts(client) -> Facts:
    rows = list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).values_list("name", "group"))
    groups: dict[str, str] = {}
    for name, group in rows:
        groups.setdefault(normal_name(name), group)
    banks = frozenset(normal_name(n) for n, g in rows if g in _BANKS)
    accounts = {
        normal_name(a.ledger_name): (str(a.pk), a.is_liability)
        for a in BankAccount.objects.filter(firm_id=client.firm_id, client=client)
    }
    return Facts(groups=groups, bank_ledgers=banks, accounts=accounts)


def _doc_name(run) -> str:
    return f"Tally import {run.pk}"


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def stage_vouchers(client, membership, user, *, data: bytes, filename: str, date_from=None, date_to=None, voucher_types=None):
    """Read ``data`` and stage a preview. Returns ``(run, reused)``.

    ``voucher_types`` says which standard type each of the firm's own voucher types counts as (``{"GST SALE": "sales"}``).
    """
    _require_rights(membership, client)
    type_map = {normal_name(k): v for k, v in (voucher_types or {}).items() if v in STANDARD_TYPES}
    digest = hashlib.sha256(data + repr(sorted(type_map.items())).encode()).hexdigest() if type_map else hashlib.sha256(data).hexdigest()
    parsed = parse_vouchers(data, filename, max_bytes=settings.MAX_TALLY_IMPORT_BYTES)
    if len(parsed.companies) > 1:
        raise TallyImportError("This file has vouchers from more than one company. Export one company at a time.")
    document = _keep_file(client, user, data, filename)
    return _stage(client, user, parsed.vouchers, parsed.skipped, digest, date_from, date_to, type_map, document)


#: A staged import waits in the queue until a person posts or discards it; it does not lapse.
QUEUE_LIFETIME = datetime.timedelta(days=3650)


def _keep_file(client, user, data: bytes, filename: str) -> Document:
    """Keep the file as uploaded, as the client's evidence (and so the queue can re-read it). One object per file, whoever uploads it."""
    digest = Document.digest(data)
    document = Document.objects.filter(firm_id=client.firm_id, client=client, sha256=digest).first()
    if document is not None:
        return document
    storage = get_storage()
    key = storage.tenant_key(client.firm_id, "clients", str(client.pk), "tally", f"{digest}{os.path.splitext(filename)[1].lower()}")
    storage.put(key, data, content_type="application/json" if filename.lower().endswith(".json") else "application/xml")
    return Document.objects.create(
        firm_id=client.firm_id,
        client=client,
        kind=DocumentKind.TALLY_EXPORT,
        original_filename=filename[:255],
        sha256=digest,
        storage_key=key,
        byte_size=len(data),
        pipeline_tier=PipelineTier.MANUAL,
        status=DocumentStatus.PARSED,
        uploaded_by=user,
    )


def _overlap(client, first, last) -> dict:
    return {
        "entries": JournalEntry.objects.filter(firm_id=client.firm_id, client=client, entry_date__gte=first, entry_date__lte=last).count(),
        "statement_rows": 0,
    }


def stage_bank_reports(client, membership, user, *, reports: list[tuple[str, bytes, object]], date_from=None, date_to=None):
    """Stage one preview from Tally bank ledger reports, each for one of the client's bank accounts. Returns ``(run, reused)``.

    Each row becomes a two-line voucher between its account's ledger and the row's other ledger, and goes through the same plan, preview,
    confirm and undo as a vouchers export. A transfer between two of the client's own accounts is printed in both accounts' reports with the
    same identity, so reports staged together write it once, with a row on each account.
    """
    _require_rights(membership, client)
    if not reports:
        raise TallyImportError("Choose at least one report.")
    merged: dict[str, ParsedVoucher] = {}
    skipped = []
    digest = hashlib.sha256()
    used: set[str] = set()
    for filename, data, account_id in reports:
        account = BankAccount.objects.filter(pk=account_id, firm_id=client.firm_id, client=client).first()
        if account is None:
            raise TallyImportError("Choose one of this client's bank accounts for each report.")
        if str(account.pk) in used:
            raise TallyImportError(f"Two reports are for {account}. Choose a different account for each report.")
        used.add(str(account.pk))
        report = parse_bank_report(data, filename, max_bytes=settings.MAX_TALLY_IMPORT_BYTES)
        digest.update(hashlib.sha256(data).digest() + str(account.pk).encode())
        for voucher in _vouchers_from_report(report, account.ledger_name):
            merged.setdefault(voucher.guid, voucher)  # the other side of a transfer is the same voucher
        skipped.extend(report.skipped)
    return _stage(client, user, list(merged.values()), skipped, digest.hexdigest(), date_from, date_to)


def _vouchers_from_report(report, bank_ledger: str) -> list[ParsedVoucher]:
    """The bank report's rows as two-line vouchers. The identity of each is the same from either bank's side."""
    seen: dict[str, int] = {}
    out = []
    for row in report.rows:
        pair = "|".join(sorted((normal_name(bank_ledger), normal_name(row.counter))))
        key = f"report|{row.date.isoformat()}|{row.number}|{abs(row.signed_paise)}|{pair}"
        seen[key] = seen.get(key, 0) + 1
        out.append(
            ParsedVoucher(
                ordinal=row.ordinal,
                guid=hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest(),
                tally_type=row.voucher_type,
                number=row.number,
                date=row.date,
                party="",
                narration=row.narration,
                reference="",
                party_gstin="",
                own_gstin="",
                lines=(
                    VoucherLine(bank_ledger, row.signed_paise, False),
                    VoucherLine(row.counter, -row.signed_paise, False),
                ),
            )
        )
    return out


def _stage(client, user, all_vouchers, skipped, digest, date_from, date_to, type_map=None, document=None):
    vouchers = [v for v in all_vouchers if (date_from is None or v.date >= date_from) and (date_to is None or v.date <= date_to)]
    if not vouchers:
        raise TallyImportError("There are no vouchers to import in this file for that period.")
    first, last = min(v.date for v in vouchers), max(v.date for v in vouchers)
    year = financial_year(first)

    through = editing.locked_through(client.pk)
    if through is not None and first <= through:
        raise editing.EntryLockedError(
            f"The books are signed off through {through:%d-%m-%Y}, so vouchers dated from {first:%d-%m-%Y} cannot be imported. "
            f"Only the client's senior CA or a firm administrator can reopen the books."
        )
    # Entries or bank rows already in these dates are a warning for the accountant to decide on, not a refusal: the same voucher
    # (by Tally's id) is never written twice, but a manual entry or an uploaded statement for the same money would be counted twice.
    overlap = _overlap(client, first, last)

    stamp = chart_stamp(client, year)
    existing = LedgerImportRun.objects.filter(
        firm_id=client.firm_id,
        client=client,
        kind=ImportKind.VOUCHERS,
        file_sha256=digest,
        status=ImportStatus.PREVIEW,
        chart_stamp=stamp,
        expires_at__gt=timezone.now(),
    ).first()
    if existing is not None:
        return existing, True

    facts = _facts(client)
    rows: list[dict] = []
    accounts_used: set[str] = set()
    counts = {"vouchers": 0, "will_post": 0, "will_make_bill": 0, "skipped": 0, "bank_waiting": 0, "bank_rows": 0, "stock_lines": 0, "by_type": {}, "unknown_types": {}, "type_map": dict(type_map or {})}
    for v in vouchers:
        plan = plan_voucher(v, facts, type_map)
        known = normal_name(v.tally_type) in STANDARD_TYPES or normal_name(v.tally_type) in (type_map or {})
        if not known:  # a type the firm made up: the person is asked what it counts as
            counts["unknown_types"][v.tally_type] = counts["unknown_types"].get(v.tally_type, 0) + 1
        counts["vouchers"] += 1
        counts["by_type"][v.tally_type] = counts["by_type"].get(v.tally_type, 0) + 1
        row = {
            "ordinal": v.ordinal, "guid": v.guid, "type": v.tally_type, "number": v.number, "date": v.date.isoformat(),
            "party": v.party, "total_paise": sum(line.signed_paise for line in v.lines if line.signed_paise > 0),
            "action": "post", "bill": False, "reason": "", "note": "",
        }
        if isinstance(plan, Planned):
            counts["will_post"] += 1
            counts["will_make_bill"] += 1 if plan.bill else 0
            row.update(
                bill=plan.bill is not None,
                note=plan.note,
                voucher_type=plan.voucher_type,
                entry_kind=plan.entry_kind,
                lines=[[line.ledger, line.signed_paise, [list(b) for b in line.bills]] for line in v.lines],
                narration=v.narration,
                reference=v.reference,
                gstin=v.party_gstin,
                own_gstin=v.own_gstin,
                figures=dataclasses.asdict(plan.bill) if plan.bill else None,
                items=(
                    [[i.name, i.unit, i.quantity, i.value_paise] for i in v.items] if plan.voucher_type in _STOCK_DIRECTION else []
                ),
                bank=(
                    {"legs": [[g.ledger, g.account_id, g.signed_paise] for g in plan.bank.legs], "counter": plan.bank.counter}
                    if plan.bank
                    else None
                ),
            )
            counts["stock_lines"] += len(v.items) if plan.voucher_type in _STOCK_DIRECTION else 0
            if plan.bank:
                counts["bank_rows"] += len(plan.bank.legs)
                accounts_used.update(g.account_id for g in plan.bank.legs)
        else:
            row["action"], row["reason"] = "skip", plan.reason
            counts["skipped"] += 1
            counts["bank_waiting"] += 1 if ("later release" in plan.reason or "bank account" in plan.reason) else 0
        rows.append(row)
    for s in skipped:
        counts["skipped"] += 1
        rows.append({
            "ordinal": s.ordinal, "guid": "", "type": "", "number": s.name, "date": "", "party": "", "total_paise": 0,
            "action": "skip", "bill": False, "reason": s.reason, "note": "",
        })
    counts["date_from"], counts["date_to"] = first.isoformat(), last.isoformat()

    overlap["statement_rows"] = (
        StatementTransaction.objects.filter(
            firm_id=client.firm_id, bank_account_id__in=accounts_used, value_date__gte=first, value_date__lte=last
        ).count()
        if accounts_used
        else 0
    )
    counts["existing_entries"], counts["existing_statement_rows"] = overlap["entries"], overlap["statement_rows"]

    run = LedgerImportRun.objects.create(
        firm_id=client.firm_id,
        client=client,
        kind=ImportKind.VOUCHERS,
        financial_year=year,
        uploaded_by=user,
        file_sha256=digest,
        source_format="xml",
        include_openings=False,
        books_from=first,
        counts=counts,
        rows=rows,
        chart_stamp=stamp,
        expires_at=timezone.now() + QUEUE_LIFETIME,
        document=document,
    )
    return run, False


# ---------------------------------------------------------------------------
# Confirming
# ---------------------------------------------------------------------------


class _Refused(Exception):
    """A rule stopped this one voucher. The message is shown against it."""


def check_postable(run: LedgerImportRun, membership, *, allow_overlap: bool = False) -> None:
    """Raise the reason this queued import cannot be posted now (rights, state, ledgers changed, entries already in its dates)."""
    client = run.client
    _require_rights(membership, client)
    if run.kind != ImportKind.VOUCHERS:
        raise TallyImportError("This is not a vouchers import.")
    if run.status != ImportStatus.PREVIEW or run.expires_at <= timezone.now():
        raise TallyImportError("This import has been discarded or has expired. Upload the file again.")
    if chart_stamp(client, run.financial_year) != run.chart_stamp:
        raise TallyRunStaleError("The client's ledgers changed since this import was read. Read it again, and then post it.")
    _recheck_period(client, run, allow_overlap)


def discard_run(run: LedgerImportRun, membership) -> LedgerImportRun:
    """Take a queued import out of the queue. The stored file stays with the client's documents."""
    _require_rights(membership, run.client)
    if run.kind != ImportKind.VOUCHERS or run.status != ImportStatus.PREVIEW:
        raise TallyImportError("Only an import still waiting to be posted can be discarded.")
    run.status = ImportStatus.DISCARDED
    run.save(update_fields=["status"])
    return run


def refresh_run(run: LedgerImportRun, membership, user, *, voucher_types=None) -> LedgerImportRun:
    """Read the stored file again against the client's ledgers as they stand now, and queue that in place of this one.

    The queue is long-lived, so the ledgers can change between reading a file and posting it. Nothing needs uploading again.
    """
    client = run.client
    _require_rights(membership, client)
    if run.kind != ImportKind.VOUCHERS or run.status != ImportStatus.PREVIEW:
        raise TallyImportError("Only an import still waiting to be posted can be read again.")
    document = run.document
    if document is None or not document.storage_key:
        raise TallyImportError("The file for this import is no longer stored, so it cannot be read again. Upload it again.")
    try:
        StorageAdapter.verify_tenant_key(document.storage_key, client.firm_id)
        data = get_storage().get(document.storage_key)
    except (PermissionError, FileNotFoundError, KeyError):
        raise TallyImportError("The file for this import is no longer stored, so it cannot be read again. Upload it again.") from None
    types = voucher_types if voucher_types is not None else run.counts.get("type_map")
    fresh, _reused = stage_vouchers(client, membership, user, data=data, filename=document.original_filename, voucher_types=types)
    if fresh.pk != run.pk:
        run.status = ImportStatus.DISCARDED
        run.save(update_fields=["status"])
    return fresh


def confirm_vouchers(run: LedgerImportRun, membership, user, *, allow_overlap: bool = False, on_progress=None) -> LedgerImportRun:
    """Write every voucher the preview marked ``post``, each in its own transaction. Idempotent.

    ``allow_overlap`` is the accountant's say-so that entries or bank rows already in these dates may stay beside the import;
    ``on_progress(done, total)`` is told as the vouchers are written.
    """
    client = run.client
    if run.status == ImportStatus.CONFIRMED:
        return run
    check_postable(run, membership, allow_overlap=allow_overlap)
    ledgers = {normal_name(a.name): a for a in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client)}
    done = set(TallyVoucher.objects.filter(firm_id=client.firm_id, client=client).values_list("guid", flat=True))
    result = {"posted": 0, "bills": 0, "skipped": 0, "failed": [], "bank_rows": 0, "unmatched_bills": 0, "stock_entries": 0}
    todo = sorted((r for r in run.rows if r["action"] == "post"), key=lambda r: (r["date"], r["ordinal"]))
    try:
        for count, row in enumerate(todo, start=1):
            if on_progress is not None and (count % 10 == 0 or count == len(todo)):
                on_progress(count - 1, len(todo))
            if row["guid"] in done:
                result["skipped"] += 1
                continue
            try:
                with transaction.atomic():
                    outcome = _write(client, user, run, row, ledgers)
            except _Refused as exc:
                result["failed"].append({"guid": row["guid"], "reason": str(exc)})
                continue
            except Exception as exc:  # one voucher must not stop the rest; its own savepoint has rolled back
                logger.warning("A Tally voucher could not be written (%s)", type(exc).__name__)
                result["failed"].append({"guid": row["guid"], "reason": "The voucher could not be written."})
                continue
            done.add(row["guid"])
            result["posted"] += 1
            result["bank_rows"] += outcome["bank_rows"]
            result["unmatched_bills"] += outcome["unmatched"]
            result["stock_entries"] += outcome["stock"]
            if outcome["bill"]:
                result["bills"] += 1
            elif outcome["bill"] is None:
                result["failed"].append({"guid": row["guid"], "reason": "Posted, but no bill was made: a duplicate invoice number."})
    finally:
        _finalize_statements(client, run)
    try:
        with transaction.atomic():
            rule_ids = learn_rules(client, run, user)
    except Exception as exc:  # learning is a bonus; it must never undo or block the books
        logger.warning("Learning from a Tally import failed (%s)", type(exc).__name__)
        rule_ids = []
    result["rules_learned"] = len(rule_ids)
    result["rule_ids"] = rule_ids
    run.status = ImportStatus.CONFIRMED
    run.result = result
    run.confirmed_by, run.confirmed_at = user, timezone.now()
    run.save(update_fields=["status", "result", "confirmed_by", "confirmed_at"])
    return run


def _recheck_period(client, run, allow_overlap: bool = False) -> None:
    """Look at the period again before anything is written: the preview's warning may have grown, and a person must have said yes to it."""
    first = datetime.date.fromisoformat(run.counts["date_from"])
    last = datetime.date.fromisoformat(run.counts["date_to"])
    entries = _overlap(client, first, last)["entries"]
    accounts = {leg[1] for r in run.rows if r.get("bank") for leg in r["bank"]["legs"]}
    statement_rows = (
        StatementTransaction.objects.filter(firm_id=client.firm_id, bank_account_id__in=accounts, value_date__gte=first, value_date__lte=last).count()
        if accounts
        else 0
    )
    if allow_overlap or not (entries or statement_rows):
        return
    parts = []
    if entries:
        parts.append(f"{entries} entries")
    if statement_rows:
        parts.append(f"{statement_rows} bank statement rows")
    raise TallyOverlapError(
        f"This client already has {' and '.join(parts)} between {first:%d-%m-%Y} and {last:%d-%m-%Y}. Importing on top can count the same money "
        f"twice. Confirm that you want to import anyway, or take the other entries out first."
    )


def _write(client, user, run, row, ledgers) -> dict:
    """Write one voucher. ``bill`` in the answer is True when a bill was made, False when none was meant, None when it clashed."""
    date = datetime.date.fromisoformat(row["date"])
    through = editing.locked_through(client.pk)
    if through is not None and date <= through:
        raise _Refused(f"The books are signed off through {through:%d-%m-%Y}.")
    figures = row.get("figures")
    bank = row.get("bank")
    year = financial_year(date)

    bill_party = _party_for(client, figures, row, ledgers) if figures else None
    line_ledgers = [ledgers[normal_name(name)] for name, _signed, _bills in row["lines"]]
    parties = {p.ledger_id: p for p in Party.objects.filter(firm_id=client.firm_id, client=client, ledger__in=line_ledgers)}
    for ledger in line_ledgers:
        if ledger.pk not in parties and ledger.group in (LedgerGroup.DEBTOR, LedgerGroup.CREDITOR):
            party = _party_of_ledger(client, ledger)
            if party is not None:
                parties[ledger.pk] = party
    if bill_party is not None:
        parties[bill_party.ledger_id] = bill_party

    narration = row["narration"] or f"{row['type']} {row['number']} (from Tally)".strip()
    txns = _bank_rows(client, user, run, row, bank, date, narration) if bank else []
    entry = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=allocate_voucher_number(client, year, row["voucher_type"]),
        financial_year=year,
        entry_date=date,
        voucher_type=row["voucher_type"],
        entry_kind=row["entry_kind"],
        narration=narration,
        source_transaction=txns[0] if txns else None,
        approved_by=user,
        approved_at=timezone.now(),
        marker=EntryMarker.NONE,
    )
    lines = [
        JournalLine.build(
            entry=entry,
            ledger_account=ledger,
            party=parties.get(ledger.pk),
            direction=Direction.DEBIT if signed > 0 else Direction.CREDIT,
            amount_paise=abs(signed),
        )
        for ledger, (_name, signed, _bills) in zip(line_ledgers, row["lines"], strict=True)
    ]
    JournalLine.objects.bulk_create(lines)
    TallyVoucher.objects.create(
        firm_id=client.firm_id, client=client, run=run, guid=row["guid"], tally_type=row["type"],
        tally_number=row["number"], entry=entry,
    )
    if bank:
        _classify_bank(user, bank, txns, entry, ledgers, parties)
    unmatched = _settle(client, lines, row["lines"])
    made = _bill(client, bill_party, entry, row, figures, date, year) if figures else False
    stock = _stock(client, user, run, row, date)
    return {"bill": made, "unmatched": unmatched, "bank_rows": len(txns), "stock": stock}


def _party_for(client, figures, row, ledgers) -> Party:
    ledger = ledgers[normal_name(figures["party_ledger"])]
    customer = figures["kind"] in (BillKind.SALES, BillKind.CREDIT_NOTE)
    role = PartyRole.CUSTOMER if customer else PartyRole.VENDOR
    party = Party.objects.filter(firm_id=client.firm_id, client=client, ledger=ledger).first()
    if party is None:
        party, _ = Party.objects.get_or_create(
            firm_id=client.firm_id, client=client, canonical_name=ledger.name, defaults={"role": role}
        )
        if party.ledger_id not in (None, ledger.pk):
            raise _Refused(f"A party named {ledger.name!r} already uses a different ledger.")
        if party.ledger_id is None:
            party.ledger = ledger
    if party.role != role and party.role != PartyRole.BOTH:
        party.role = PartyRole.BOTH
    if row.get("gstin") and not party.gstin:
        party.set_gstin(row["gstin"])
    party.save()
    return party


def _stock(client, user, run, row, date) -> int:
    """The movements of an item invoice's stock items, for the stock register. Goods in or out depends on the voucher's type."""
    direction = _STOCK_DIRECTION.get(row["voucher_type"])
    items = row.get("items") or []
    if direction is None or not items:
        return 0
    note = f"Tally {row['type']} {row['number']}"[:300]
    StockEntry.objects.bulk_create(
        [
            StockEntry(
                firm_id=client.firm_id,
                client=client,
                kind=StockEntryKind.TALLY,
                entry_date=date,
                direction=direction,
                name=name[:200],
                unit=unit[:16],
                quantity=Decimal(quantity),
                value_paise=value,
                note=note,
                created_by=user,
                run=run,
            )
            for name, unit, quantity, value in items
        ]
    )
    return len(items)


def _party_of_ledger(client, ledger) -> Party | None:
    """A debtor or creditor ledger is a party, so a payment on it can settle that party's bills. None when the name is taken."""
    role = PartyRole.CUSTOMER if ledger.group == LedgerGroup.DEBTOR else PartyRole.VENDOR
    party, _ = Party.objects.get_or_create(
        firm_id=client.firm_id, client=client, canonical_name=ledger.name, defaults={"role": role}
    )
    if party.ledger_id is None and not Party.objects.filter(ledger=ledger).exists():
        party.ledger = ledger
        party.save(update_fields=["ledger"])
    return party if party.ledger_id == ledger.pk else None


def _bill(client, party, entry, row, f, date, year) -> bool | None:
    purchase = f["kind"] in (BillKind.PURCHASE, BillKind.DEBIT_NOTE)
    reference = (row["number"] or row["reference"])[:64]
    identity = supplier_identity(party.gstin, party.pk) if purchase else supplier_identity(row.get("own_gstin", ""), client.pk)
    own = normalise_gstin(row.get("own_gstin", ""))
    try:
        with transaction.atomic():
            Bill.objects.create(
                firm_id=client.firm_id,
                client=client,
                party=party,
                kind=f["kind"],
                direction=Direction.CREDIT if f["kind"] in (BillKind.PURCHASE, BillKind.CREDIT_NOTE) else Direction.DEBIT,
                reference=reference,
                bill_date=date,
                booked_on=date,
                financial_year=year,
                taxable_paise=f["taxable_paise"],
                cgst_paise=f["cgst_paise"],
                sgst_paise=f["sgst_paise"],
                igst_paise=f["igst_paise"],
                cess_paise=f["cess_paise"],
                round_off_paise=f["round_off_paise"],
                tds_paise=f.get("tds_paise", 0),
                total_paise=f["total_paise"],
                entry=entry,
                invoice_key=invoice_key(client.firm_id, identity, reference),
                own_gstin_hash=blind_index(own, client.firm_id, CRYPTO_PURPOSE) if own else "",
            )
    except IntegrityError:
        return None
    return True


def _settle(client, line_objects, row_lines) -> int:
    """Settle bills the way Tally's bill allocations say. Returns how many references could not be applied."""
    unmatched = 0
    for obj, (_name, _signed, bills) in zip(line_objects, row_lines, strict=True):
        if obj.party_id is None:
            continue
        for ref, kind, paise in bills:
            if kind == "New Ref":
                continue  # this line is the bill itself
            bill = None
            if kind == "Agst Ref":
                bill = (
                    Bill.objects.filter(firm_id=client.firm_id, client=client, party_id=obj.party_id, reference=ref[:64])
                    .exclude(direction=obj.direction)
                    .first()
                )
            try:
                against = min(paise, open_amount(bill), line_unallocated(obj)) if bill is not None else 0
                if against > 0:
                    allocate(obj, amount_paise=against, bill=bill)
                rest = min(paise - against, line_unallocated(obj))
                if rest > 0:
                    allocate(obj, amount_paise=rest, kind=AllocationKind.ADVANCE if kind == "Advance" else AllocationKind.ON_ACCOUNT)
                if bill is None and kind == "Agst Ref":
                    unmatched += 1  # named a bill that is not in these books: left on account for a person to apply
            except BillingError:
                unmatched += 1
    return unmatched


# ---------------------------------------------------------------------------
# Bank rows
# ---------------------------------------------------------------------------


def _bank_rows(client, user, run, row, bank, date, narration) -> list[StatementTransaction]:
    rows = []
    for index, (_ledger, account_id, signed) in enumerate(bank["legs"]):
        account = BankAccount.objects.get(pk=account_id, firm_id=client.firm_id, client=client)
        statement = _statement_for(client, user, run, account, date)
        if StatementTransaction.objects.filter(bank_account=account, value_date=date).exclude(statement=statement).exists():
            raise _Refused(f"{account} already has statement rows on {date:%d-%m-%Y}.")
        rows.append(
            StatementTransaction.objects.create(
                firm_id=client.firm_id,
                statement=statement,
                bank_account=account,
                row_number=statement.transactions.count() + 1,
                value_date=date,
                narration=narration,
                # Statement columns are the bank's: money out is a debit. The books' sign is the other way round.
                debit_paise=-signed if signed < 0 else 0,
                credit_paise=signed if signed > 0 else 0,
                balance_paise=0,  # worked out when the run ends, from the rows that were written
                dedupe_hash=hashlib.sha256(f"tally:{row['guid']}:{index}:{account_id}".encode()).hexdigest(),
            )
        )
    return rows


def _statement_for(client, user, run, account, date) -> Statement:
    digest = hashlib.sha256(f"tally-import:{run.pk}:{account.pk}".encode()).hexdigest()
    document = Document.objects.filter(firm_id=client.firm_id, client=client, sha256=digest).first()
    if document is not None:
        return document.statement
    document = Document.objects.create(
        firm_id=client.firm_id,
        client=client,
        kind=DocumentKind.TALLY_EXPORT,
        original_filename=_doc_name(run),
        sha256=digest,
        pipeline_tier=PipelineTier.MANUAL,
        status=DocumentStatus.PARSED,
        uploaded_by=user,
    )
    return Statement.objects.create(
        firm_id=client.firm_id,
        document=document,
        bank_account=account,
        period_start=date,
        period_end=date,
        opening_balance_paise=account.opening_balance_paise or 0,
        closing_balance_paise=0,
        total_debit_paise=0,
        total_credit_paise=0,
        transaction_count=0,
        parser="tally-import",
    )


def _classify_bank(user, bank, txns, entry, ledgers, parties) -> None:
    """Place each row where Tally put it, as a person's decision, so the assistant can learn from it and nothing is re-asked."""
    now = timezone.now()
    legs = bank["legs"]
    if len(legs) == 2:  # between two of the client's own accounts: each row points at the other account's ledger
        placed = [ledgers[normal_name(legs[1][0])], ledgers[normal_name(legs[0][0])]]
    else:
        placed = [ledgers[normal_name(bank["counter"])]]
    for index, (txn, ledger) in enumerate(zip(txns, placed, strict=True)):
        party = parties.get(ledger.pk)
        TransactionClassification.objects.create(
            firm_id=txn.firm_id,
            transaction=txn,
            ledger=ledger,
            party=party,
            method=ClassificationMethod.REVIEWED,
            confidence=1.0,
            review_band=ReviewBand.HIGH,
            needs_review=False,
            reviewed_by=user,
            reviewed_at=now,
            counterparty=party.canonical_name if party else "",
            is_self_transfer=len(legs) == 2,
            book_narration=entry.narration,
            rationale="Imported from Tally.",
            mirrored_entry_id=entry.pk if index == 1 else None,
        )


def _finalize_statements(client, run) -> None:
    """Work each placeholder statement's running balance, period and totals out from the rows that were actually written."""
    documents = Document.objects.filter(
        firm_id=client.firm_id, client=client, kind=DocumentKind.TALLY_EXPORT, original_filename=_doc_name(run)
    )
    for document in documents:
        try:
            statement = document.statement
        except ObjectDoesNotExist:
            continue
        rows = list(statement.transactions.order_by("value_date", "row_number"))
        if not rows:
            continue
        balance = statement.opening_balance_paise
        owed = statement.bank_account.is_liability  # a loan or card statement prints what is owed, which a debit raises
        for txn in rows:
            balance += (txn.debit_paise - txn.credit_paise) if owed else (txn.credit_paise - txn.debit_paise)
            txn.balance_paise = balance
        StatementTransaction.objects.bulk_update(rows, ["balance_paise"])
        statement.period_start, statement.period_end = rows[0].value_date, rows[-1].value_date
        statement.closing_balance_paise = balance
        statement.total_debit_paise = sum(t.debit_paise for t in rows)
        statement.total_credit_paise = sum(t.credit_paise for t in rows)
        statement.transaction_count = len(rows)
        statement.save()


# ---------------------------------------------------------------------------
# Undoing
# ---------------------------------------------------------------------------


def undo_run(run: LedgerImportRun, membership, user) -> LedgerImportRun:
    """Take every entry a confirmed run wrote back out, while nothing outside the run depends on them."""
    client = run.client
    _require_rights(membership, client)
    if run.kind != ImportKind.VOUCHERS or run.status != ImportStatus.CONFIRMED:
        raise TallyImportError("Only an applied vouchers import can be undone.")
    with transaction.atomic():
        links = list(
            TallyVoucher.objects.select_for_update(of=("self",))
            .filter(firm_id=client.firm_id, client=client, run=run)
            .select_related("entry")
        )
        entry_ids = [link.entry_id for link in links]
        for link in links:
            editing.require_editable(link.entry)
            bill = Bill.objects.filter(entry=link.entry).first()
            # Payments this same import wrote are taken back with it; one a person has entered since is not.
            if bill is not None and bill.allocations.exclude(line__entry_id__in=entry_ids).exists():
                raise TallyImportError(
                    f"Invoice {bill.reference!r} has a payment or adjustment applied to it, so this import cannot be "
                    f"undone. Release the payment first."
                )
        BillAllocation.objects.filter(line__entry_id__in=entry_ids).delete()
        StockEntry.objects.filter(firm_id=client.firm_id, client=client, run=run).delete()
        for link in links:
            entry = JournalEntry.objects.select_for_update().get(pk=link.entry_id)
            editing.record_change(
                entry, ChangeAction.REMOVED, actor=user, before=editing.snapshot(entry), note="Tally import undone"
            )
            Bill.objects.filter(entry=entry).delete()
            link.delete()
            entry.lines.all().delete()
            entry.delete()
        # Rules this import learned that nothing has used yet go back with it.
        ClassificationRule.objects.filter(
            firm_id=client.firm_id, client=client, pk__in=run.result.get("rule_ids", []), hit_count=0
        ).delete()
        # The placeholder statements, their rows and the rows' placements go with the entries they carried.
        Document.objects.filter(
            firm_id=client.firm_id, client=client, kind=DocumentKind.TALLY_EXPORT, original_filename=_doc_name(run)
        ).delete()
        run.status = ImportStatus.DISCARDED
        run.result = {**run.result, "undone": len(links)}
        run.save(update_fields=["status", "result"])
    return run
