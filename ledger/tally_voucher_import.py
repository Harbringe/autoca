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
    TallyVoucher,
)
from ledger.tally_import import (
    PREVIEW_LIFETIME,
    TallyImportError,
    TallyRunStaleError,
    _require_rights,
    chart_stamp,
)
from ledger.tally_learning import learn_rules
from ledger.tally_parse import normal_name
from ledger.tally_plan import Facts, Planned, plan_voucher
from ledger.tally_vouchers import parse_vouchers

logger = logging.getLogger("autoca.tally")

_BANKS = (LedgerGroup.BANK, LedgerGroup.BANK_OD)


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


def stage_vouchers(client, membership, user, *, data: bytes, filename: str, date_from=None, date_to=None):
    """Read ``data`` and stage a preview. Returns ``(run, reused)``."""
    _require_rights(membership, client)
    digest = hashlib.sha256(data).hexdigest()
    parsed = parse_vouchers(data, filename, max_bytes=settings.MAX_TALLY_IMPORT_BYTES)
    if len(parsed.companies) > 1:
        raise TallyImportError("This file has vouchers from more than one company. Export one company at a time.")
    vouchers = [
        v for v in parsed.vouchers if (date_from is None or v.date >= date_from) and (date_to is None or v.date <= date_to)
    ]
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
    if JournalEntry.objects.filter(firm_id=client.firm_id, client=client, entry_date__gte=first, entry_date__lte=last).exists():
        raise TallyImportError(
            f"This client already has entries between {first:%d-%m-%Y} and {last:%d-%m-%Y}. History can only be imported "
            f"into a period with nothing posted."
        )

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
    counts = {"vouchers": 0, "will_post": 0, "will_make_bill": 0, "skipped": 0, "bank_waiting": 0, "bank_rows": 0, "by_type": {}}
    for v in vouchers:
        plan = plan_voucher(v, facts)
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
                bank=(
                    {"legs": [[g.ledger, g.account_id, g.signed_paise] for g in plan.bank.legs], "counter": plan.bank.counter}
                    if plan.bank
                    else None
                ),
            )
            if plan.bank:
                counts["bank_rows"] += len(plan.bank.legs)
                accounts_used.update(g.account_id for g in plan.bank.legs)
        else:
            row["action"], row["reason"] = "skip", plan.reason
            counts["skipped"] += 1
            counts["bank_waiting"] += 1 if ("later release" in plan.reason or "bank account" in plan.reason) else 0
        rows.append(row)
    for s in parsed.skipped:
        counts["skipped"] += 1
        rows.append({
            "ordinal": s.ordinal, "guid": "", "type": "", "number": s.name, "date": "", "party": "", "total_paise": 0,
            "action": "skip", "bill": False, "reason": s.reason, "note": "",
        })
    counts["date_from"], counts["date_to"] = first.isoformat(), last.isoformat()

    if accounts_used and StatementTransaction.objects.filter(
        firm_id=client.firm_id, bank_account_id__in=accounts_used, value_date__gte=first, value_date__lte=last
    ).exists():
        raise TallyImportError(
            f"A bank account in this file already has statement rows between {first:%d-%m-%Y} and {last:%d-%m-%Y}. "
            f"Importing the bank vouchers on top would count them twice. Remove that statement first."
        )

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
        expires_at=timezone.now() + PREVIEW_LIFETIME,
    )
    return run, False


# ---------------------------------------------------------------------------
# Confirming
# ---------------------------------------------------------------------------


class _Refused(Exception):
    """A rule stopped this one voucher. The message is shown against it."""


def confirm_vouchers(run: LedgerImportRun, membership, user) -> LedgerImportRun:
    """Write every voucher the preview marked ``post``, each in its own transaction. Idempotent."""
    client = run.client
    _require_rights(membership, client)
    if run.kind != ImportKind.VOUCHERS:
        raise TallyImportError("This is not a vouchers import.")
    if run.status == ImportStatus.CONFIRMED:
        return run
    if run.status != ImportStatus.PREVIEW or run.expires_at <= timezone.now():
        raise TallyImportError("This preview has expired. Upload the file again.")
    if chart_stamp(client, run.financial_year) != run.chart_stamp:
        raise TallyRunStaleError("The client's ledgers changed since this preview was made. Upload the file again.")

    _recheck_period(client, run)
    ledgers = {normal_name(a.name): a for a in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client)}
    done = set(TallyVoucher.objects.filter(firm_id=client.firm_id, client=client).values_list("guid", flat=True))
    result = {"posted": 0, "bills": 0, "skipped": 0, "failed": [], "bank_rows": 0, "unmatched_bills": 0}
    todo = sorted((r for r in run.rows if r["action"] == "post"), key=lambda r: (r["date"], r["ordinal"]))
    try:
        for row in todo:
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


def _recheck_period(client, run) -> None:
    """The preview said the period was empty; it may not be any more. Looked at again before anything is written."""
    first = datetime.date.fromisoformat(run.counts["date_from"])
    last = datetime.date.fromisoformat(run.counts["date_to"])
    if JournalEntry.objects.filter(firm_id=client.firm_id, client=client, entry_date__gte=first, entry_date__lte=last).exists():
        raise TallyRunStaleError("Entries were posted for these dates since the preview was made. Upload the file again.")
    accounts = {leg[1] for r in run.rows if r.get("bank") for leg in r["bank"]["legs"]}
    if accounts and StatementTransaction.objects.filter(
        firm_id=client.firm_id, bank_account_id__in=accounts, value_date__gte=first, value_date__lte=last
    ).exists():
        raise TallyRunStaleError("A bank statement was uploaded for these dates since the preview was made. Upload the file again.")


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
    return {"bill": made, "unmatched": unmatched, "bank_rows": len(txns)}


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
        for txn in rows:
            balance += txn.credit_paise - txn.debit_paise
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
