"""Bringing a client's Tally vouchers in, exactly as Tally had them.

Same shape as ``ledger.tally_import``: staging is mutable and the books are not. ``stage_vouchers`` reads the file, plans
every voucher, and writes one :class:`~ledger.models.LedgerImportRun` -- a preview, nothing else. ``confirm_vouchers`` writes
each voucher in its own transaction, and ``undo_run`` takes a whole run back out. Nothing here logs a name; the run records
counts and who.

The lines of a voucher are never rebuilt (see ``ledger.tally_plan``): the books must equal Tally's. No file is kept, so a
staged row carries everything its confirm needs.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from classify.models import CRYPTO_PURPOSE, LedgerAccount, LedgerGroup, Party, PartyRole
from core.crypto import blind_index
from core.fy import financial_year
from core.identity import invoice_key, normalise_gstin, supplier_identity
from ledger import editing
from ledger.approval import allocate_voucher_number
from ledger.models import (
    Bill,
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
    return Facts(groups=groups, bank_ledgers=banks)


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
    counts = {"vouchers": 0, "will_post": 0, "will_make_bill": 0, "skipped": 0, "bank_waiting": 0, "by_type": {}}
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
                lines=[[line.ledger, line.signed_paise] for line in v.lines],
                narration=v.narration,
                reference=v.reference,
                gstin=v.party_gstin,
                own_gstin=v.own_gstin,
                figures=dataclasses.asdict(plan.bill) if plan.bill else None,
            )
        else:
            row["action"], row["reason"] = "skip", plan.reason
            counts["skipped"] += 1
            counts["bank_waiting"] += 1 if "later release" in plan.reason else 0
        rows.append(row)
    for s in parsed.skipped:
        counts["skipped"] += 1
        rows.append({
            "ordinal": s.ordinal, "guid": "", "type": "", "number": s.name, "date": "", "party": "", "total_paise": 0,
            "action": "skip", "bill": False, "reason": s.reason, "note": "",
        })
    counts["date_from"], counts["date_to"] = first.isoformat(), last.isoformat()

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

    ledgers = {normal_name(a.name): a for a in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client)}
    done = set(TallyVoucher.objects.filter(firm_id=client.firm_id, client=client).values_list("guid", flat=True))
    result = {"posted": 0, "bills": 0, "skipped": 0, "failed": []}
    todo = sorted((r for r in run.rows if r["action"] == "post"), key=lambda r: (r["date"], r["ordinal"]))
    for row in todo:
        if row["guid"] in done:
            result["skipped"] += 1
            continue
        try:
            with transaction.atomic():
                made_bill = _write(client, user, run, row, ledgers)
        except _Refused as exc:
            result["failed"].append({"guid": row["guid"], "reason": str(exc)})
            continue
        except Exception as exc:  # one voucher must not stop the rest; its own savepoint has rolled back
            logger.warning("A Tally voucher could not be written (%s)", type(exc).__name__)
            result["failed"].append({"guid": row["guid"], "reason": "The voucher could not be written."})
            continue
        done.add(row["guid"])
        result["posted"] += 1
        if made_bill:
            result["bills"] += 1
        elif made_bill is None:
            result["failed"].append({"guid": row["guid"], "reason": "Posted, but no bill was made: a duplicate invoice number."})
    run.status = ImportStatus.CONFIRMED
    run.result = result
    run.confirmed_by, run.confirmed_at = user, timezone.now()
    run.save(update_fields=["status", "result", "confirmed_by", "confirmed_at"])
    return run


def _write(client, user, run, row, ledgers) -> bool | None:
    """Write one voucher. True when a bill was made, False when none was meant, None when the bill clashed."""
    date = datetime.date.fromisoformat(row["date"])
    through = editing.locked_through(client.pk)
    if through is not None and date <= through:
        raise _Refused(f"The books are signed off through {through:%d-%m-%Y}.")
    figures = row.get("figures")
    party = _party_for(client, figures, row, ledgers) if figures else None
    year = financial_year(date)
    entry = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=allocate_voucher_number(client, year, row["voucher_type"]),
        financial_year=year,
        entry_date=date,
        voucher_type=row["voucher_type"],
        entry_kind=row["entry_kind"],
        narration=row["narration"] or f"{row['type']} {row['number']} (from Tally)".strip(),
        approved_by=user,
        approved_at=timezone.now(),
        marker=EntryMarker.NONE,
    )
    party_key = normal_name(figures["party_ledger"]) if figures else None
    lines = [
        JournalLine.build(
            entry=entry,
            ledger_account=ledgers[normal_name(name)],
            party=party if normal_name(name) == party_key else None,
            direction=Direction.DEBIT if signed > 0 else Direction.CREDIT,
            amount_paise=abs(signed),
        )
        for name, signed in row["lines"]
    ]
    JournalLine.objects.bulk_create(lines)
    TallyVoucher.objects.create(
        firm_id=client.firm_id, client=client, run=run, guid=row["guid"], tally_type=row["type"],
        tally_number=row["number"], entry=entry,
    )
    if not figures:
        return False
    return _bill(client, party, entry, row, figures, date, year)


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


# ---------------------------------------------------------------------------
# Undoing
# ---------------------------------------------------------------------------


def undo_run(run: LedgerImportRun, membership, user) -> LedgerImportRun:
    """Take every entry a confirmed run wrote back out, while nothing depends on them."""
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
        for link in links:
            editing.require_editable(link.entry)
            bill = Bill.objects.filter(entry=link.entry).first()
            if bill is not None and bill.allocations.exists():
                raise TallyImportError(
                    f"Invoice {bill.reference!r} has a payment or adjustment applied to it, so this import cannot be "
                    f"undone. Release the payment first."
                )
        for link in links:
            entry = JournalEntry.objects.select_for_update().get(pk=link.entry_id)
            editing.record_change(
                entry, ChangeAction.REMOVED, actor=user, before=editing.snapshot(entry), note="Tally import undone"
            )
            Bill.objects.filter(entry=entry).delete()
            link.delete()
            entry.lines.all().delete()
            entry.delete()
        run.status = ImportStatus.DISCARDED
        run.result = {**run.result, "undone": len(links)}
        run.save(update_fields=["status", "result"])
    return run
