"""Changing and removing entries while the books are still a working draft.

Until a senior signs the books off (``ledger.books``), an entry is not final: the
normal work of a CA is to look at what the AI posted, remove what is wrong and
correct what is close. This module is that work, and its one hard rule is that
**nothing changes without leaving its previous state behind** -- ``EntryChange``
records who, when, why and the complete before, so a removed entry can be read
back and an edit can be explained.

After sign-off none of this is possible. The database refuses (``ledger.0008``),
and these functions check first only so the refusal reads as an explanation
instead of a trigger's error message. What replaces editing there is a visible
correcting entry (``approval.correct``).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from classify.models import ClassificationMethod, TransactionClassification
from ledger.models import (
    BillAllocation,
    ChangeAction,
    EntryChange,
    EntryKind,
    EntryMarker,
    JournalEntry,
    JournalLine,
)


class EntryLockedError(RuntimeError):
    """The entry is inside books a senior has signed off."""


class WrongEntryKindError(RuntimeError):
    """A bank-row edit was attempted on an entry that did not come from a bank row."""


def require_bank_entry(entry) -> None:
    """Revising and removing here work through the entry's bank row, which a voucher entry does not have.

    A purchase, sales or note voucher is changed through its bill (``ledger.billing.remove_bill``). Refusing here stops
    one kind of entry being pushed down the other's path, which would otherwise fail on a missing statement row, or worse,
    succeed on the wrong thing.
    """
    if entry.entry_kind != EntryKind.BANK:
        raise WrongEntryKindError(
            f"This is a {entry.get_entry_kind_display().lower()}, not a bank entry. Change it through its bill."
        )


def locked_through(client_id):
    """The date the client's books are signed off through, read fresh.

    Read from the database rather than off a Client instance held by the caller,
    which may be from before somebody signed the books off a moment ago.
    """
    from core.models import Client

    return (
        Client.objects.filter(pk=client_id).values_list("signed_off_through", flat=True).first()
    )


def is_locked(entry) -> bool:
    through = locked_through(entry.client_id)
    return through is not None and entry.entry_date <= through


def require_editable(entry) -> None:
    if is_locked(entry):
        raise EntryLockedError(
            f"This entry is dated {entry.entry_date:%d-%m-%Y}, inside books signed off "
            f"through {locked_through(entry.client_id):%d-%m-%Y}. Signed-off books can no "
            f"longer be changed; record a correcting entry dated after the sign-off, or ask "
            f"a senior to reopen the books."
        )


def snapshot(entry) -> dict:
    """The entry as it stands, in a form that can be stored and read back."""
    return {
        "id": str(entry.pk),
        "entry_no": entry.entry_no,
        "voucher_type": entry.voucher_type,
        "entry_date": entry.entry_date.isoformat(),
        "narration": entry.narration,
        "marker": entry.marker,
        "lines": [
            {
                "ledger": line.ledger_account.name,
                "ledger_id": str(line.ledger_account_id),
                "party_id": str(line.party_id) if line.party_id else None,
                "direction": line.direction,
                "amount_paise": line.amount_paise,
                "rcm": line.rcm,
                "tds_section": line.tds_section,
                # What this line was settling, so a payment's allocations are not lost when it is edited or removed.
                "allocations": [
                    {"bill": str(a.bill_id) if a.bill_id else None, "kind": a.kind, "amount_paise": a.amount_paise}
                    for a in line.allocations.all()
                ],
            }
            for line in entry.lines.select_related("ledger_account").order_by("-signed_paise")
        ],
    }


def record_change(entry, action, *, actor=None, before, after=None, note="") -> EntryChange:
    return EntryChange.objects.create(
        firm_id=entry.firm_id,
        client_id=entry.client_id,
        entry_id=entry.pk,
        voucher_type=entry.voucher_type,
        entry_no=entry.entry_no,
        entry_date=entry.entry_date,
        action=action,
        before=before,
        after=after or {},
        note=note[:500],
        actor=actor,
    )


def _release_mirrors(entry) -> None:
    """Other rows that pointed at this entry as "already posted" are unposted again.

    A transfer between two of the client's own accounts is written once, by
    whichever side is approved first; the other side records that entry's id
    instead of writing its own. Take the entry away and that row has nothing
    behind it, so it goes back to waiting for a decision.
    """
    TransactionClassification.objects.filter(
        firm_id=entry.firm_id, mirrored_entry_id=entry.pk
    ).update(mirrored_entry_id=None, needs_review=True)


@transaction.atomic
def revise_in_place(
    entry, treatment, *, actor=None, narration=None, action=ChangeAction.EDITED, note="",
    method=ClassificationMethod.REVIEWED, marker=EntryMarker.NONE, rule=None,
) -> JournalEntry:
    """Give an unsigned entry a different treatment, replacing its lines.

    ``actor`` is None when the AI is applying a lesson it learned, in which case
    ``method`` is RULE and ``marker`` says so, so the change can be found.
    Everything the entry was is kept in the change log first.
    """
    from ledger import approval

    # Re-read under a lock. The caller's copy may predate a renumbering at
    # sign-off (or another edit), and saving a stale voucher number back over a
    # fresh one would quietly undo it -- or collide with the entry that now
    # holds that number.
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    require_bank_entry(entry)
    require_editable(entry)
    approval._require_ledger_in_use(treatment.ledger)
    approval.require_not_own_bank_ledger(entry, treatment.ledger)

    classification = entry.source_transaction.classification
    before = snapshot(entry)

    classification.apply(
        treatment,
        method=method,
        confidence=(
            1.0 if method == ClassificationMethod.REVIEWED
            else (rule.confidence if rule is not None else classification.confidence)
        ),
        rule=rule,
        user=actor,
    )
    # Moved onto a party's own account: the line must name that party, which is how its position and the open items read it.
    if classification.ledger is not None and classification.ledger.is_party_account:
        if classification.party_id != classification.ledger.party_record.pk:
            classification.party = classification.ledger.party_record
    if method == ClassificationMethod.REVIEWED:
        classification.needs_review = False
        classification.reviewed_at = timezone.now()
    classification.save()

    changed = ["narration", "marker"]
    new_type = approval.voucher_type_for(classification)
    if new_type != entry.voucher_type:
        # A different voucher type is a different numbering series, and a
        # transfer that stops being one no longer backs the row that mirrored it.
        _release_mirrors(entry)
        entry.entry_no = approval.allocate_voucher_number(entry.client, entry.financial_year, new_type)
        entry.voucher_type = new_type
        changed += ["entry_no", "voucher_type"]

    # A payment that settled bills stops settling them: they reopen, and the change log has what was allocated. Whoever
    # edited it settles it again (``ledger.settlement.settle_entry``); until then it is an open item.
    BillAllocation.objects.filter(line__entry=entry).delete()
    entry.lines.all().delete()
    lines = approval._double_entry(entry, classification)
    if entry.supersedes_id:
        # This entry is itself a correction: it carries the reversal of the entry it replaced
        # as well as the new treatment. Rewriting it must keep the reversal, or the original
        # -- still in the books -- is counted a second time.
        lines = approval.reversal_lines(entry, entry.supersedes) + lines
    JournalLine.objects.bulk_create(lines)

    if narration is not None:
        entry.narration = narration
    entry.marker = marker
    entry.save(update_fields=changed)

    record_change(
        entry, action, actor=actor, before=before, after=snapshot(entry), note=note
    )
    return entry


@transaction.atomic
def remove_entry(entry, *, actor, note="") -> None:
    """Take an unsigned entry out of the books. Its row goes back to the queue.

    The classification is left as it was -- still placed, still the AI's or a
    person's decision -- but no longer posted, so it reappears among the rows
    waiting for approval instead of vanishing. The entry itself survives only in
    the change log, which is why that record is append-only.
    """
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    require_bank_entry(entry)
    require_editable(entry)
    before = snapshot(entry)
    record_change(entry, ChangeAction.REMOVED, actor=actor, before=before, note=note)

    _release_mirrors(entry)
    TransactionClassification.objects.filter(
        firm_id=entry.firm_id, transaction_id=entry.source_transaction_id
    ).update(needs_review=True)
    # Whatever the payment settled reopens; the change log recorded the allocations just above.
    BillAllocation.objects.filter(line__entry=entry).delete()
    entry.lines.all().delete()
    entry.delete()
