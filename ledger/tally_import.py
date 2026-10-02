"""Bringing a client's chart of accounts and opening balances in from Tally.

Two steps, and the line between them is the one the whole product is built on:
**staging is mutable, the books are not.**

``stage_upload`` reads the file (``ledger.tally_parse``), compares it with the
client's chart, and writes one :class:`~ledger.models.LedgerImportRun` -- a
preview, nothing else. ``confirm_run`` applies exactly what the person chose,
once, in one transaction. A conflict is never settled for them: a ledger whose
group differs, two spellings of one name, a bank opening that disagrees with the
one already confirmed, a group of the firm's own that we cannot place -- each
needs an answer before anything is written.

Opening balances are not journal entries (see ``LedgerOpening``). Where a ledger
is one of the client's bank accounts, ``BankAccount.opening_balance_paise``
already holds that number, so the import writes it there, through
``confirm_opening_balance`` and its lock rule, and stores no second copy.

Nothing here logs or audits a name: the run records counts and who, and the
audit trail records the request.
"""

from __future__ import annotations

import datetime
import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from banking.ingest import confirm_opening_balance
from classify.models import LedgerAccount, LedgerGroup, LedgerStatus
from classify.seeds import SEED_LEDGERS, rename_account_ledger
from core.access import require_chart_import
from core.fy import fy_bounds
from core.rbac import require_permission
from ledger import editing
from ledger.models import ImportStatus, JournalEntry, JournalLine, LedgerImportRun, LedgerOpening
from ledger.reports import OPENING_DIFFERENCE, PROFIT_BROUGHT_FORWARD
from ledger.tally_parse import (
    ParsedMasters,
    TallyParseError,
    TallyTooLargeError,
    normal_name,
    parse_masters,
    path_text,
    resolve_group,
)

__all__ = [
    "TallyConflictsUnresolvedError",
    "TallyImportError",
    "TallyParseError",
    "TallyRunStaleError",
    "TallyTooLargeError",
    "TallyYearMismatchError",
    "confirm_run",
    "stage_upload",
]

PREVIEW_LIFETIME = datetime.timedelta(days=7)

#: Names the system keeps for itself. A Tally file naming one is never allowed to create or
#: rename it; a seeded ledger of the same name is adopted if the groups agree.
SYSTEM_ONLY = {normal_name(PROFIT_BROUGHT_FORWARD), normal_name(OPENING_DIFFERENCE)}
RESERVED = {normal_name(name) for name, _group in SEED_LEDGERS} | SYSTEM_ONLY

# Choices a person can make on a row.
KEEP_OURS = "keep_ours"
TAKE_TALLY = "take_tally"
USE_TALLY_NAME = "use_tally_name"
USE_THIS_SPELLING = "use_this_spelling"
SKIP = "skip"
GROUP = "group"
USE_TALLY_BANK = "use_tally"
KEEP_BANK = "keep_bank"

ALL_CHOICES = (KEEP_OURS, TAKE_TALLY, USE_TALLY_NAME, USE_THIS_SPELLING, SKIP, GROUP)
BANK_CHOICES = (USE_TALLY_BANK, KEEP_BANK, SKIP)


class TallyImportError(RuntimeError):
    """A rule of the import refused the step. The message says what to change."""


class TallyYearMismatchError(RuntimeError):
    """The file's balances are not at the start of the year the person chose."""


class TallyRunStaleError(RuntimeError):
    """The preview no longer describes the client's books."""


class TallyConflictsUnresolvedError(RuntimeError):
    """Something in the preview still needs the person's decision."""

    def __init__(self, rows: list[int]):
        self.rows = rows
        shown = ", ".join(str(r + 1) for r in rows[:10]) + (" ..." if len(rows) > 10 else "")
        super().__init__(
            f"{len(rows)} line{'s' if len(rows) != 1 else ''} still need{'s' if len(rows) == 1 else ''} "
            f"your choice before anything is imported (preview lines {shown})."
        )


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def stage_upload(
    client, membership, user, *, data: bytes, filename: str, financial_year: int, include_openings: bool = True
) -> tuple[LedgerImportRun, bool]:
    """Read ``data`` and stage a preview. Returns ``(run, reused)``.

    The same file for the same year, with the chart unchanged since, is the same
    preview: uploading twice creates nothing new.
    """
    _require_rights(membership, client)
    _refuse_if_locked(client, financial_year)

    digest = hashlib.sha256(data).hexdigest()
    stamp = chart_stamp(client, financial_year)
    existing = LedgerImportRun.objects.filter(
        firm_id=client.firm_id,
        client=client,
        financial_year=financial_year,
        file_sha256=digest,
        include_openings=include_openings,
        status=ImportStatus.PREVIEW,
        chart_stamp=stamp,
        expires_at__gt=timezone.now(),
    ).first()
    if existing is not None:
        return existing, True

    parsed = parse_masters(data, filename, max_bytes=settings.MAX_TALLY_IMPORT_BYTES)
    start, _end = fy_bounds(financial_year)
    if include_openings and parsed.books_from and parsed.books_from != start:
        raise TallyYearMismatchError(
            f"This file's balances are as at {parsed.books_from:%d-%m-%Y}, the date this Tally company's "
            f"books begin, not {start:%d-%m-%Y}, the start of FY {financial_year}-{(financial_year + 1) % 100:02d}. "
            f"Opening balances taken from it would be wrong. Export the Trial Balance as at the start of the "
            f"year instead, or import the chart only."
        )

    rows, counts = _classify(client, parsed, financial_year, include_openings)
    run = LedgerImportRun.objects.create(
        firm_id=client.firm_id,
        client=client,
        financial_year=financial_year,
        uploaded_by=user,
        file_sha256=digest,
        source_format=parsed.source_format,
        include_openings=include_openings,
        books_from=parsed.books_from,
        counts=counts,
        rows=rows,
        chart_stamp=stamp,
        expires_at=timezone.now() + PREVIEW_LIFETIME,
    )
    return run, False


def chart_stamp(client, financial_year: int) -> str:
    """A fingerprint of everything a preview was compared against."""
    ledgers = sorted(
        (str(pk), name, group, status)
        for pk, name, group, status in LedgerAccount.objects.filter(
            firm_id=client.firm_id, client=client
        ).values_list("pk", "name", "group", "status")
    )
    banks = sorted(
        (a.ledger_name, a.opening_balance_paise, str(a.opening_as_of))
        for a in client.bank_accounts.all()
    )
    openings = sorted(
        (str(ledger_id), paise)
        for ledger_id, paise in LedgerOpening.objects.filter(
            firm_id=client.firm_id, client=client, financial_year=financial_year
        ).values_list("ledger_id", "signed_paise")
    )
    return hashlib.sha256(json.dumps([ledgers, banks, openings], default=str).encode()).hexdigest()


def _classify(client, parsed: ParsedMasters, financial_year: int, include_openings: bool):
    ledgers = list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).order_by("name"))
    by_key: dict[str, LedgerAccount] = {}
    for ledger in ledgers:
        by_key.setdefault(normal_name(ledger.name), ledger)
    by_name = {ledger.name: ledger for ledger in ledgers}
    posted = dict(
        JournalLine.objects.filter(firm_id=client.firm_id, ledger_account__client=client)
        .order_by()
        .values("ledger_account_id")
        .annotate(n=Count("id"))
        .values_list("ledger_account_id", "n")
    )
    banks = {normal_name(a.ledger_name): a for a in client.bank_accounts.all() if a.ledger_name}

    staged: list[dict] = [
        _row(ordinal=line.ordinal, name=line.name, action="skipped", reason=line.reason)
        for line in parsed.skipped
    ]
    for item in parsed.ledgers:
        key = normal_name(item.name)
        resolution = resolve_group(item.parent, parsed.groups)
        row = _row(
            ordinal=item.ordinal,
            name=item.name,
            alias=item.alias,
            tally_group=item.parent,
            tally_group_path=path_text(resolution.path),
            our_group=resolution.group,
            opening_paise=item.opening_paise,
        )
        if key in SYSTEM_ONLY:
            row.update(
                action="skipped",
                reason=(
                    "Tally's own balancing line, not a ledger. Whatever it carries appears under "
                    "Profit & Loss A/c or Difference in opening balances in the reports."
                ),
            )
        else:
            row.update(_place(item.name, key, resolution, by_name.get(item.name) or by_key.get(key), posted))
        staged.append(row)
    # Source order, with the lines that could not be read in place among the rest.
    staged.sort(key=lambda r: r["ordinal"])

    first_seen: dict[str, int] = {}
    for index, row in enumerate(staged):
        row["row"] = index
        if row["action"] == "skipped":
            continue
        key = normal_name(row["name"])
        if key not in first_seen:
            first_seen[key] = index
            continue
        usable = row["action"] in ("create", "match")
        row.update(
            inner={k: row.get(k) for k in ("action", "ledger_id", "our_group")},
            action="conflict",
            reason=(
                f"Appears more than once in the file (also line {first_seen[key] + 1}); "
                f"names that differ only by case or spaces are one ledger."
            ),
            conflict={
                "kind": "duplicate_in_file",
                "pair_row": first_seen[key],
                "choices": [SKIP] + ([USE_THIS_SPELLING] if usable else []),
                "default": SKIP,
            },
        )

    if include_openings:
        for row in staged:
            if row["action"] != "skipped":
                row["bank"] = _bank_panel(row, banks)

    entries_in_year = JournalEntry.objects.filter(
        firm_id=client.firm_id,
        client=client,
        entry_date__gte=fy_bounds(financial_year)[0],
        entry_date__lte=fy_bounds(financial_year)[1],
    ).count()
    debit = sum(r["opening_paise"] for r in staged if r["action"] != "skipped" and r["opening_paise"] > 0)
    credit = -sum(r["opening_paise"] for r in staged if r["action"] != "skipped" and r["opening_paise"] < 0)
    counts = {
        "create": sum(r["action"] == "create" for r in staged),
        "match": sum(r["action"] == "match" for r in staged),
        "conflict": sum(r["action"] == "conflict" for r in staged),
        "needs_group": sum(r["action"] == "needs_group" for r in staged),
        "skipped": sum(r["action"] == "skipped" for r in staged),
        "with_opening": sum(bool(r["opening_paise"]) for r in staged if r["action"] != "skipped"),
        "bank_conflicts": sum(
            1 for r in staged if r.get("bank") and r["bank"]["status"] == "conflict"
        ),
        "debit_paise": debit if include_openings else 0,
        "credit_paise": credit if include_openings else 0,
        "difference_paise": (debit - credit) if include_openings else 0,
        "entries_in_year": entries_in_year,
    }
    return staged, counts


def _row(**fields) -> dict:
    row = {
        "row": 0,
        "ordinal": 0,
        "name": "",
        "alias": None,
        "tally_group": "",
        "tally_group_path": None,
        "our_group": None,
        "opening_paise": 0,
        "action": "skipped",
        "reason": "",
        "ledger_id": None,
        "ledger_name": None,
        "ledger_group": None,
        "posted_lines": 0,
        "conflict": None,
        "bank": None,
    }
    row.update(fields)
    return row


def _place(name: str, key: str, resolution, ledger: LedgerAccount | None, posted) -> dict:
    """What this line would do to the client's chart, before anyone has chosen anything."""
    reserved = key in RESERVED
    if ledger is None:
        if reserved:
            return {
                "action": "skipped",
                "reason": "A name the system keeps for itself; it is created when it is needed.",
            }
        if resolution.group is None:
            return {
                "action": "needs_group",
                "reason": (
                    "Its group is one of the firm's own in Tally, which this system cannot place. "
                    "Say which of our groups it belongs to."
                ),
                "conflict": {"kind": "needs_group", "choices": [GROUP, SKIP], "default": None},
            }
        return {"action": "create"}

    known = {
        "ledger_id": str(ledger.pk),
        "ledger_name": ledger.name,
        "ledger_group": ledger.group,
        "posted_lines": posted.get(ledger.pk, 0),
    }
    if ledger.status != LedgerStatus.ACTIVE:
        known["reason"] = "A ledger that was only proposed or rejected; importing it makes it a normal ledger."
    if ledger.name != name:
        return {
            **known,
            "action": "conflict",
            "reason": (
                f"We already have {ledger.name!r}, which differs from {name!r} only by case or spacing. "
                f"They would split the books if both existed."
            ),
            "conflict": {
                "kind": "name_variant",
                "choices": [KEEP_OURS, SKIP] if reserved else [KEEP_OURS, USE_TALLY_NAME, SKIP],
                "default": KEEP_OURS,
            },
        }
    if resolution.group is not None and resolution.group != ledger.group:
        refuse_move = reserved or known["posted_lines"] > 0
        return {
            **known,
            "action": "conflict",
            "reason": (
                f"Tally puts it under a different group than ours "
                f"({LedgerGroup(resolution.group).label} against {LedgerGroup(ledger.group).label})."
                + (" Entries are already posted to it, so its group cannot change." if known["posted_lines"] else "")
            ),
            "conflict": {
                "kind": "group_differs",
                "choices": [KEEP_OURS, SKIP] if refuse_move else [KEEP_OURS, TAKE_TALLY, SKIP],
                "default": KEEP_OURS,
            },
        }
    return {**known, "action": "match"}


def _bank_panel(row: dict, banks) -> dict | None:
    """The client's bank account this line is, if any, and whether the two openings agree."""
    key = normal_name(row["ledger_name"] or row["name"])
    account = banks.get(key) or banks.get(normal_name(row["name"]))
    if account is None:
        return None
    ours, theirs = account.opening_balance_paise, row["opening_paise"]
    if ours is None and not theirs:
        # A file that gives no opening for it is not evidence that the books began at zero.
        status, choices, default = "nothing", [], None
    elif ours is None:
        status, choices, default = "propose", [USE_TALLY_BANK, SKIP], USE_TALLY_BANK
    elif ours == theirs:
        status, choices, default = "agree", [], None
    else:
        status, choices, default = "conflict", [USE_TALLY_BANK, KEEP_BANK], None
    return {
        "account_id": str(account.pk),
        "label": account.ledger_name,
        "ours_paise": ours,
        "tally_paise": theirs,
        "status": status,
        "choices": choices,
        "default": default,
    }


# ---------------------------------------------------------------------------
# Confirming
# ---------------------------------------------------------------------------


def confirm_run(run: LedgerImportRun, membership, user, resolutions: list[dict]) -> LedgerImportRun:
    """Apply what the person chose. Idempotent: a run already applied is returned as it is.

    ``resolutions`` is a list of ``{"row": int, "choice": str, "group": str?, "bank": str?}``.
    """
    client = run.client
    _require_rights(membership, client)
    with transaction.atomic():
        run = LedgerImportRun.objects.select_for_update().get(pk=run.pk, firm_id=run.firm_id)
        if run.status == ImportStatus.CONFIRMED:
            return run
        if run.status != ImportStatus.PREVIEW or run.expires_at <= timezone.now():
            raise TallyRunStaleError(
                "This preview has expired or was discarded. Upload the file again to make a new one."
            )
        _refuse_if_locked(client, run.financial_year)
        if run.chart_stamp != chart_stamp(client, run.financial_year):
            raise TallyRunStaleError(
                "This client's ledgers or opening balances have changed since the preview was made. "
                "Upload the file again so the preview matches what is there now."
            )
        _apply(run, user, resolutions)
        run.status = ImportStatus.CONFIRMED
        run.confirmed_by = user
        run.confirmed_at = timezone.now()
        run.save(update_fields=["status", "confirmed_by", "confirmed_at", "result"])
    return run


def _choices(run: LedgerImportRun, resolutions: list[dict]) -> tuple[dict[int, dict], set[int]]:
    rows = {r["row"]: r for r in run.rows}
    chosen: dict[int, dict] = {}
    for item in resolutions:
        index = item["row"]
        row = rows.get(index)
        if row is None:
            raise ValidationError(f"There is no line {index + 1} in this preview.")
        if index in chosen:
            raise ValidationError(f"Line {index + 1} has more than one choice.")
        conflict = row.get("conflict")
        if item.get("choice"):
            if not conflict or item["choice"] not in conflict["choices"]:
                raise ValidationError(f"{item['choice']!r} is not an option for line {index + 1}.")
            if item["choice"] == GROUP and item.get("group") not in LedgerGroup.values:
                raise ValidationError(f"Line {index + 1} needs one of our groups.")
        if item.get("bank"):
            panel = row.get("bank")
            if not panel or item["bank"] not in panel["choices"]:
                raise ValidationError(f"{item['bank']!r} is not an option for the bank figure on line {index + 1}.")
        chosen[index] = item

    dropped: set[int] = set()
    for index, item in chosen.items():
        if item.get("choice") == USE_THIS_SPELLING:
            pair = rows[index]["conflict"]["pair_row"]
            if pair in dropped:
                raise ValidationError(f"Two lines both claim to replace line {pair + 1}.")
            dropped.add(pair)
    return chosen, dropped


def _apply(run: LedgerImportRun, user, resolutions: list[dict]) -> None:
    client = run.client
    chosen, dropped = _choices(run, resolutions)

    unresolved = []
    for row in run.rows:
        index = row["row"]
        if row["action"] == "skipped" or index in dropped:
            continue
        item = chosen.get(index, {})
        if row["action"] in ("conflict", "needs_group") and not item.get("choice"):
            unresolved.append(index)
        elif run.include_openings and row.get("bank") and row["bank"]["status"] == "conflict":
            if item.get("choice") != SKIP and not item.get("bank"):
                unresolved.append(index)
    if unresolved:
        raise TallyConflictsUnresolvedError(unresolved)

    ledgers = {str(l.pk): l for l in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client)}
    start = fy_bounds(run.financial_year)[0]
    tally = {"created": 0, "matched": 0, "renamed": 0, "regrouped": 0, "openings": 0, "bank_openings": 0, "skipped": 0}
    applied: list[int] = []
    created_total = 0

    for row in run.rows:
        index = row["row"]
        if row["action"] == "skipped" or index in dropped:
            tally["skipped"] += 1
            continue
        item = chosen.get(index, {})
        choice = item.get("choice")
        kind = (row.get("conflict") or {}).get("kind")
        duplicate = kind == "duplicate_in_file"
        placement = row["inner"] if duplicate else row

        if choice == SKIP:
            tally["skipped"] += 1
            continue

        if kind == "needs_group" or (not kind or duplicate) and placement["action"] == "create":
            group = item["group"] if kind == "needs_group" else placement["our_group"]
            ledger, created = LedgerAccount.objects.get_or_create(
                firm_id=client.firm_id, client=client, name=row["name"], defaults={"group": group}
            )
            created_total += created
            tally["created" if created else "matched"] += 1
            ledgers[str(ledger.pk)] = ledger
        else:
            ledger = ledgers[placement["ledger_id"]]
            tally["matched"] += 1
            if choice == TAKE_TALLY:
                _regroup(ledger, row["our_group"])
                tally["regrouped"] += 1
            elif choice == USE_TALLY_NAME:
                _rename(ledger, row["name"])
                tally["renamed"] += 1

        _remember_tally_names(ledger, row)

        if not run.include_openings:
            continue
        panel = row.get("bank")
        if panel:
            if _apply_bank(client, panel, item, row["opening_paise"], start):
                tally["bank_openings"] += 1
                applied.append(row["opening_paise"])
            continue
        if _apply_opening(run, ledger, row["opening_paise"]):
            tally["openings"] += 1
            applied.append(row["opening_paise"])

    debit = sum(p for p in applied if p > 0)
    credit = -sum(p for p in applied if p < 0)
    run.result = {
        **tally,
        "debit_paise": debit,
        "credit_paise": credit,
        "difference_paise": debit - credit,
    }
    if created_total:
        from teams import activity
        from teams.models import ActivityKind

        activity.record(
            firm_id=client.firm_id,
            user=user,
            kind=ActivityKind.LEDGER_CREATED,
            client=client,
            quantity=created_total,
            subject_id=run.pk,
        )


def _remember_tally_names(ledger: LedgerAccount, row: dict) -> None:
    ledger.tally_name = row["name"]
    ledger.alias = row.get("alias") or ledger.alias
    ledger.tally_group_path = row.get("tally_group_path")
    fields = ["tally_name", "alias", "tally_group_path"]
    if ledger.status != LedgerStatus.ACTIVE:
        ledger.status = LedgerStatus.ACTIVE
        ledger.is_active = True
        fields += ["status", "is_active"]
    ledger.save(update_fields=fields)


def _regroup(ledger: LedgerAccount, group: str) -> None:
    posted = JournalLine.objects.filter(firm_id=ledger.firm_id, ledger_account=ledger).count()
    if posted:
        raise TallyImportError(
            f"{ledger.name!r} has {posted} posted line{'s' if posted != 1 else ''}, so its group cannot change."
        )
    ledger.group = group
    ledger.save(update_fields=["group"])


def _rename(ledger: LedgerAccount, name: str) -> None:
    """Rename with its entries; a bank account's ledger keeps its link to the account."""
    from banking.models import BankAccount

    account = BankAccount.objects.filter(
        firm_id=ledger.firm_id, client_id=ledger.client_id, ledger_name=ledger.name
    ).first()
    if account is not None:
        rename_account_ledger(account, name)
        ledger.refresh_from_db(fields=["name"])
        return
    clash = LedgerAccount.objects.filter(
        firm_id=ledger.firm_id, client_id=ledger.client_id, name=name
    ).exclude(pk=ledger.pk)
    if clash.exists():
        from classify.seeds import LedgerRenameError

        raise LedgerRenameError(f"This client already has a ledger named {name!r}.")
    ledger.name = name
    ledger.save(update_fields=["name"])


def _apply_bank(client, panel: dict, item: dict, tally_paise: int, start: datetime.date) -> bool:
    from banking.models import BankAccount

    if panel["status"] == "agree":
        return False
    choice = item.get("bank") or (USE_TALLY_BANK if panel["status"] == "propose" else None)
    if choice != USE_TALLY_BANK:
        return False
    account = BankAccount.objects.get(pk=panel["account_id"], firm_id=client.firm_id, client=client)
    confirm_opening_balance(account, balance_paise=tally_paise, as_of=start)
    return True


def _apply_opening(run: LedgerImportRun, ledger: LedgerAccount, paise: int) -> bool:
    """Store (or clear) the ledger's opening for the year. True when one is now stored."""
    scope = LedgerOpening.objects.filter(
        firm_id=run.firm_id, client_id=run.client_id, ledger=ledger, financial_year=run.financial_year
    )
    if not paise:
        scope.delete()
        return False
    LedgerOpening.objects.update_or_create(
        firm_id=run.firm_id,
        client_id=run.client_id,
        ledger=ledger,
        financial_year=run.financial_year,
        defaults={"signed_paise": paise, "run": run},
    )
    return True


# ---------------------------------------------------------------------------
# Rules shared by both steps
# ---------------------------------------------------------------------------


def _require_rights(membership, client) -> None:
    require_permission(membership, "ledger.import")
    require_chart_import(membership, client)


def _refuse_if_locked(client, financial_year: int) -> None:
    through = editing.locked_through(client.pk)
    start = fy_bounds(financial_year)[0]
    if through is not None and through >= start:
        raise editing.EntryLockedError(
            f"This client's books are signed off through {through:%d-%m-%Y}, which covers the start of "
            f"FY {financial_year}-{(financial_year + 1) % 100:02d}, so its opening balances and chart can no "
            f"longer be imported. Only the client's senior CA or a firm administrator can reopen the books."
        )
