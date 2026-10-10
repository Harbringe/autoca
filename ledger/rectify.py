"""Putting right an entry that is inside signed-off books.

Sealed books are never edited. A bank entry can be corrected through its statement row (``ledger.approval.correct``); a bill or a
voucher cannot, because its lines are not one classification. What a CA needs for those is the ordinary accounting answer: a
journal, dated in the open period, that moves an amount from the wrong ledger to the right one, with the reason written on it.
The original stays exactly as it was, the journal names it, and the change log of the original records that it was rectified.

Deliberately narrow: only ledgers that are neither a party's own account nor a bank or cash ledger can be moved between. A
party's balance is settled through allocations and a bank balance is proved by the statement, so neither is changed by a journal
that says "reclassify".
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from classify.models import LedgerStatus
from core.access import require_sign_off
from core.fy import financial_year
from ledger import approval, editing
from ledger.models import (
    ChangeAction,
    Direction,
    EntryChange,
    EntryKind,
    JournalEntry,
    JournalLine,
    VoucherType,
)


class RectifyError(ValueError):
    """The rectification cannot be made. The message says what to change."""


def _check_ledger(ledger, name: str) -> None:
    if ledger.status != LedgerStatus.ACTIVE:
        raise RectifyError(f"{ledger.name!r} is not a ledger in use.")
    if ledger.is_party_account or ledger.is_bank_or_cash:
        raise RectifyError(
            f"{ledger.name!r} is a party's or a bank/cash ledger. Those are put right through the party's allocations or the "
            f"statement, not by a reclassifying journal."
        )


@transaction.atomic
def rectify(entry, *, from_ledger, to_ledger, amount_paise: int, reason: str, membership, on: datetime.date | None = None):
    """Move ``amount_paise`` of what ``entry`` put on ``from_ledger`` to ``to_ledger``, by a journal dated ``on`` (default today)."""
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    client = entry.client
    require_sign_off(membership, client)
    if entry.firm_id != membership.firm_id:
        raise RectifyError("That entry is not in this firm.")
    reason = " ".join(str(reason or "").split())
    if len(reason) < 5:
        raise RectifyError("Say why the entry is being rectified (at least a few words).")
    if not editing.is_locked(entry):
        raise RectifyError("This entry is not inside signed-off books, so it can be changed directly instead.")
    if amount_paise <= 0:
        raise RectifyError("The amount to move must be more than zero.")
    if from_ledger.pk == to_ledger.pk:
        raise RectifyError("Choose a different ledger to move it to.")
    for ledger in (from_ledger, to_ledger):
        if ledger.client_id != entry.client_id:
            raise RectifyError(f"{ledger.name!r} belongs to another client.")
        _check_ledger(ledger, ledger.name)

    original = [line for line in entry.lines.all() if line.ledger_account_id == from_ledger.pk]
    if not original:
        raise RectifyError(f"{from_ledger.name!r} has no line on {entry.get_voucher_type_display()} {entry.entry_no}.")
    direction = original[0].direction
    on_that_side = sum(line.amount_paise for line in original if line.direction == direction)
    already = sum(
        (change.after or {}).get("amount_paise", 0)
        for change in EntryChange.objects.filter(entry_id=entry.pk, action=ChangeAction.RECTIFIED)
        if (change.after or {}).get("from") == from_ledger.name
    )
    if amount_paise > on_that_side - already:
        raise RectifyError("That is more than the entry put on that ledger (less anything already moved).")

    on = on or timezone.localdate()
    through = editing.locked_through(client.pk)
    if through is not None and on <= through:
        raise RectifyError(f"The books are sealed through {through:%d-%m-%Y}; date the rectification after that.")

    year = financial_year(on)
    journal = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=approval.allocate_voucher_number(client, year, VoucherType.JOURNAL),
        financial_year=year,
        entry_date=on,
        voucher_type=VoucherType.JOURNAL,
        entry_kind=EntryKind.VOUCHER,
        narration=(
            f"Being rectification of {entry.get_voucher_type_display()} {entry.entry_no} dated {entry.entry_date:%d-%m-%Y}: "
            f"{amount_paise / 100:,.2f} moved from {from_ledger.name} to {to_ledger.name}. {reason}"
        )[:500],
        approved_by=membership.user,
        approved_at=timezone.now(),
    )
    out, into = (
        (Direction.CREDIT, Direction.DEBIT) if direction == Direction.DEBIT else (Direction.DEBIT, Direction.CREDIT)
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine.build(entry=journal, ledger_account=from_ledger, direction=out, amount_paise=amount_paise),
            JournalLine.build(entry=journal, ledger_account=to_ledger, direction=into, amount_paise=amount_paise),
        ]
    )
    before = editing.snapshot(entry)
    editing.record_change(
        entry,
        ChangeAction.RECTIFIED,
        actor=membership.user,
        before=before,
        after={"rectified_by": str(journal.pk), "from": from_ledger.name, "to": to_ledger.name, "amount_paise": amount_paise},
        note=reason,
    )
    return journal
