"""Getting a client's books from a working draft to signed off.

The shape of the work, as a firm actually does it:

1. The AI fills the books from the statement. A CA works through them --
   removing what is wrong, correcting what is close -- while nothing is final.
2. When the CA is done they **request approval**.
3. A senior looks at the books as a whole -- the trial balance, the balance
   sheet -- and either **returns** them with a note or **approves** them. Approval
   is "yes, this is good": it locks nothing. Entries stay editable, and a change
   made after it is reported so the approval cannot go stale unseen.
4. At the end of the period the client's schedule names (quarterly, half-yearly
   or yearly) the senior **seals** the books through that date. The seal is the
   permanent lock: from then on the database itself refuses to change anything
   dated up to it (``ledger.0008``). The seal is what this module has always
   called ``sign_off``; the old name is kept so nothing that locks was renamed.

The state is not stored anywhere; it is read off the record of what happened
(``BooksEvent``) and the client's ``signed_off_through`` date. A stored state
can disagree with the history that supposedly produced it, and the history is
what an auditor asks for.

Two things happen at sign-off that do not happen at any other moment. Voucher
numbers are made contiguous, because a CA is free to delete entries while the
books are a draft and that leaves gaps, and gaps in a signed set of vouchers are
what an auditor opens with. And the lock date is advanced -- last, after the
renumbering, because renumbering is an UPDATE the lock would otherwise refuse.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction

from classify.engine import review_queue
from core.access import can_see_client, require_sign_off
from core.models import Client
from core.rbac import require_permission
from ledger.models import (
    BooksAction,
    BooksEvent,
    ChangeAction,
    EntryChange,
    EntryMarker,
    JournalEntry,
    VoucherSequence,
)

#: Big enough to clear any real voucher number, so renumbering can park every
#: entry out of the way before giving each its final number. Without the parking
#: step, renumbering 3 -> 2 while 2 still exists breaks the unique constraint
#: mid-way even though the end state is fine.
_PARK_OFFSET = 1_000_000


class BooksError(RuntimeError):
    """The books are not in a state that allows this."""


class NotReadyError(BooksError):
    """Rows are still waiting for a decision, so the books are incomplete."""

    def __init__(self, waiting: int):
        self.waiting = waiting
        super().__init__(
            f"{waiting} transaction{'s' if waiting != 1 else ''} still {'needs' if waiting == 1 else 'need'} a decision. "
            f"Approval can be requested once every row is placed and posted."
        )


class AiEntriesUncheckedError(BooksError):
    """Entries the assistant posted or changed have not been looked at by a person."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(
            f"{count} entr{'y' if count == 1 else 'ies'} the assistant posted or changed "
            f"{'has' if count == 1 else 'have'} not been checked by a person. "
            f"Check {'it' if count == 1 else 'them'}, then mark {'it' if count == 1 else 'them'} as "
            f"checked, before signing off."
        )


class NothingRequestedError(BooksError):
    """A senior can only sign off books that somebody has submitted."""


class NotApprovedError(BooksError):
    """The books are sealed only after a senior has approved them, and only if nothing has changed since."""


class NotASealDateError(BooksError):
    """Books are sealed on the dates the client's schedule names, once they have passed."""


@dataclass(frozen=True)
class BooksStatus:
    #: The date everything up to is locked, or None if nothing is signed off.
    signed_off_through: datetime.date | None
    #: A CA has asked for approval and the senior has not yet answered.
    review_pending: bool
    requested_by: str = ""
    requested_at: datetime.datetime | None = None
    #: The senior's note when they last returned the books, if that was the last word.
    returned_note: str = ""
    #: The senior has said the books are good through this date. Not a lock: see ``approve``.
    approved_through: datetime.date | None = None
    approved_by: str = ""
    approved_at: datetime.datetime | None = None
    #: Entries dated inside the approved period that were added, changed or removed after the approval.
    changed_since_approval: int = 0

    @property
    def is_locked(self) -> bool:
        return self.signed_off_through is not None


def status(client) -> BooksStatus:
    events = list(
        BooksEvent.objects.filter(firm_id=client.firm_id, client=client)
        .select_related("actor")
        .order_by("created_at", "id")
    )
    through = (
        Client.objects.filter(pk=client.pk).values_list("signed_off_through", flat=True).first()
    )
    last = events[-1] if events else None
    pending = last is not None and last.action == BooksAction.REQUESTED

    # Approval is read off the history like everything else: the latest APPROVED, until the senior returns the books or
    # they are reopened (either way the "yes, this is good" no longer stands).
    approval = None
    for event in events:
        if event.action == BooksAction.APPROVED:
            approval = event
        elif event.action in (BooksAction.RETURNED, BooksAction.REOPENED):
            approval = None
    changed = _changed_since(client, approval) if approval is not None else 0
    return BooksStatus(
        signed_off_through=through,
        review_pending=pending,
        requested_by=(last.actor.email if pending and last.actor else ""),
        requested_at=last.created_at if pending else None,
        returned_note=last.note if last is not None and last.action == BooksAction.RETURNED else "",
        approved_through=approval.through_date if approval else None,
        approved_by=(approval.actor.email if approval and approval.actor else ""),
        approved_at=approval.created_at if approval else None,
        changed_since_approval=changed,
    )


def opening_fingerprint(client) -> str:
    """What the books start from, as one value: every bank account's opening balance and every imported ledger opening.

    These move the trial balance and the balance sheet without being journal entries, so an entry-based check alone would
    let one change after an approval unnoticed.
    """
    import hashlib

    from banking.models import BankAccount
    from ledger.models import LedgerOpening

    parts = [
        f"bank|{a.pk}|{a.opening_balance_paise}|{a.opening_as_of}"
        for a in BankAccount.objects.filter(firm_id=client.firm_id, client=client).order_by("pk")
    ]
    parts += [
        f"open|{o.ledger_id}|{o.financial_year}|{o.signed_paise}"
        for o in LedgerOpening.objects.filter(firm_id=client.firm_id, client=client).order_by("ledger_id", "financial_year")
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _changed_since(client, approval) -> int:
    """How many entries inside the approved period were added, changed or removed after the senior approved.

    Computed, never stored: an entry created after the approval, or any logged edit or removal after it, dated inside the
    period. Counted by entry, so an edit that also made a correcting entry counts once.
    """
    through = approval.through_date
    touched = set(
        JournalEntry.objects.filter(
            firm_id=client.firm_id, client=client, entry_date__lte=through, created_at__gt=approval.created_at
        ).values_list("pk", flat=True)
    )
    touched |= set(
        EntryChange.objects.filter(
            firm_id=client.firm_id, client=client, entry_date__lte=through, created_at__gt=approval.created_at
        ).values_list("entry_id", flat=True)
    )
    # A starting figure changed since the approval counts as one change (the opening, not an entry).
    drifted = bool(approval.fingerprint) and approval.fingerprint != opening_fingerprint(client)
    return len(touched) + (1 if drifted else 0)


# ---------------------------------------------------------------------------
# When a period may be sealed
# ---------------------------------------------------------------------------

_STEPS = {"QUARTERLY": 3, "HALF_YEARLY": 6, "YEARLY": 12}


def seal_dates(client, *, upto: datetime.date, after: datetime.date | None = None) -> list[datetime.date]:
    """The dates the client's schedule seals on, up to ``upto`` and after ``after``, oldest first.

    Books run April to March, so a quarterly client seals on 30 June, 30 September, 31 December and 31 March; a
    half-yearly one on 30 September and 31 March; a yearly one on 31 March.
    """
    step = _STEPS.get(client.close_period, 3)
    out = []
    for year in range(upto.year - 2, upto.year + 1):
        for months in range(step, 13, step):
            month = 4 + months  # April start; the period ends the day before this month's first
            y, m = (year, month) if month <= 12 else (year + 1, month - 12)
            end = datetime.date(y, m, 1) - datetime.timedelta(days=1)
            if end <= upto and (after is None or end > after):
                out.append(end)
    return sorted(set(out))



def ready_to_seal(current: BooksStatus, latest_due: datetime.date | None) -> bool:
    """Approved through the latest sealing date that has passed, with nothing changed since the approval."""
    return bool(
        latest_due
        and current.approved_through
        and current.approved_through >= latest_due
        and not current.changed_since_approval
    )


def _waiting(client, *, through: datetime.date | None = None) -> int:
    """Rows not yet posted, optionally only those dated on or before ``through``."""
    rows = review_queue(client)
    if through is not None:
        rows = rows.filter(transaction__value_date__lte=through)
    return rows.count()


def _event(client, action, *, actor, through=None, note="", fingerprint="") -> BooksEvent:
    return BooksEvent.objects.create(
        firm_id=client.firm_id, client=client, action=action,
        through_date=through, note=note[:1000], actor=actor, fingerprint=fingerprint,
    )


@transaction.atomic
def request_review(client, membership, note: str = "") -> BooksEvent:
    """A CA says they are finished and the senior may look."""
    require_permission(membership, "books.request")
    if not can_see_client(membership, client):
        raise PermissionDenied("You are not assigned to this client.")

    current = status(client)
    if current.review_pending:
        raise BooksError("Approval has already been requested and is waiting for a senior.")
    waiting = _waiting(client)
    if waiting:
        raise NotReadyError(waiting)
    return _event(client, BooksAction.REQUESTED, actor=membership.user, note=note)


@transaction.atomic
def return_for_changes(client, membership, note: str) -> BooksEvent:
    """The senior sends the books back, with what needs fixing."""
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    if not status(client).review_pending:
        raise NothingRequestedError("Nothing has been submitted for sign-off.")
    if not (note or "").strip():
        raise BooksError("Say what needs to change, so the CA knows what to fix.")
    return _event(client, BooksAction.RETURNED, actor=membership.user, note=note)


def _require_ready(client, through: datetime.date, previous: datetime.date | None) -> None:
    """What must hold before books are approved or sealed through ``through``: nothing waiting, nothing unchecked."""
    waiting = _waiting(client, through=through)
    if waiting:
        # A row dated inside the period that is not posted can never be posted once the period locks -- the database would
        # refuse -- so it has to be dealt with first, not left behind the lock.
        raise NotReadyError(waiting)

    unchecked = JournalEntry.objects.filter(
        firm_id=client.firm_id, client=client, entry_date__lte=through
    ).exclude(marker=EntryMarker.NONE)
    if previous is not None:
        # Markers on entries an earlier seal already locked can no longer be cleared.
        unchecked = unchecked.filter(entry_date__gt=previous)
    if unchecked.exists():
        raise AiEntriesUncheckedError(unchecked.count())

    # Where the books and a document or the bank disagree, someone has fixed it or said why it can stand.
    from ledger import close

    close.require_clear(client)


def _latest_entry_date(client) -> datetime.date | None:
    return (
        JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
        .order_by("-entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )


@transaction.atomic
def approve(client, membership, *, through: datetime.date | None = None, note: str = "") -> BooksEvent:
    """The senior says the books are good. This locks nothing.

    Entries stay editable. What approval gives is a dated statement of what the senior looked at, and a promise that any
    later change inside that period is reported (``BooksStatus.changed_since_approval``), so the approval cannot silently go
    stale. Sealing the period, later, is what locks it, and needs this approval to be current.

    Allowed when a CA has asked for review, or when an earlier approval has had changes since (a re-approval).
    """
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    current = status(client)
    stale = current.approved_through is not None and current.changed_since_approval > 0
    if not current.review_pending and not stale:
        raise NothingRequestedError("Nothing has been submitted for approval. A CA requests approval first.")

    previous = current.signed_off_through
    latest = _latest_entry_date(client)
    if latest is None:
        raise BooksError("There are no entries to approve.")
    through = through or latest
    if previous is not None and through <= previous:
        raise BooksError(f"The books are already sealed through {previous:%d-%m-%Y}.")
    _require_ready(client, through, previous)
    return _event(
        client, BooksAction.APPROVED, actor=membership.user, through=through, note=note,
        fingerprint=opening_fingerprint(client),
    )


@transaction.atomic
def sign_off(
    client, membership, *, through: datetime.date | None = None, note: str = "", strict: bool = False
) -> BooksEvent:
    """Seal the books: the permanent lock.

    ``through`` defaults to the date of the latest entry. Everything up to and
    including it is locked; entries dated later stay a working draft, so the
    next month's statement can be worked while this one is closed.

    ``strict`` is how people seal (the API passes it): the date must be one the client's schedule names and must have
    passed, and a senior's approval must cover it with nothing changed since. Without it the older rule stands (a review
    was requested), which is what the engine's own tests and any internal use rely on.
    """
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    current = status(client)
    previous = current.signed_off_through

    if strict:
        if current.approved_through is None:
            raise NotApprovedError(
                "A senior has not approved these books yet. Approve them first; sealing locks them for good."
            )
        reachable = seal_dates(client, upto=min(current.approved_through, datetime.date.today()), after=previous)
        if through is None:
            if not reachable:
                nxt = seal_dates(client, upto=datetime.date.today() + datetime.timedelta(days=400), after=previous)
                raise NotASealDateError(
                    "No sealing date has been reached that the approval covers."
                    + (f" The next sealing date is {nxt[0]:%d-%m-%Y}." if nxt else "")
                )
            through = reachable[-1]
        elif through not in reachable:
            raise NotASealDateError(
                f"{through:%d-%m-%Y} is not a date this client's books can be sealed through. "
                + (
                    "Sealing dates available now: " + ", ".join(f"{d:%d-%m-%Y}" for d in reachable) + "."
                    if reachable
                    else "None has been reached yet that the approval covers."
                )
            )
        if current.changed_since_approval:
            raise NotApprovedError(
                f"{current.changed_since_approval} entr{'y has' if current.changed_since_approval == 1 else 'ies have'} "
                f"changed since the senior approved. Approve again before sealing."
            )
    elif not current.review_pending:
        raise NothingRequestedError(
            "Nothing has been submitted for sign-off. A CA requests approval first."
        )

    latest = _latest_entry_date(client)
    if latest is None:
        raise BooksError("There are no entries to sign off.")
    through = through or latest
    if previous is not None and through <= previous:
        raise BooksError(f"The books are already signed off through {previous:%d-%m-%Y}.")

    _require_ready(client, through, previous)

    _renumber(client, membership.user, after=previous)
    Client.objects.filter(pk=client.pk).update(signed_off_through=through)
    client.signed_off_through = through
    return _event(client, BooksAction.SIGNED_OFF, actor=membership.user, through=through, note=note)


def _renumber(client, actor, *, after: datetime.date | None) -> int:
    """Make voucher numbers contiguous for everything not yet signed off.

    While the books were a draft entries were deleted and re-typed, so the
    sequence has holes. Renumbered here, in date order per financial year and
    voucher type, continuing from the last already-signed number. Returns how
    many entries changed number; each is recorded in the change log.
    """
    entries = JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
    scope = entries if after is None else entries.filter(entry_date__gt=after)
    changed = 0

    # order_by() matters: JournalEntry's default ordering would otherwise join the DISTINCT,
    # returning one pair per entry rather than one per voucher type, and every group would be
    # renumbered once per entry in it -- minutes, for a year of bank statements.
    for (year, voucher_type) in scope.order_by().values_list("financial_year", "voucher_type").distinct():
        floor = 0
        if after is not None:
            floor = max(
                entries.filter(
                    financial_year=year, voucher_type=voucher_type, entry_date__lte=after
                ).values_list("entry_no", flat=True),
                default=0,
            )
        group = list(
            scope.filter(financial_year=year, voucher_type=voucher_type)
            .order_by("entry_date", "created_at", "id")
        )
        moves = [(entry, floor + offset) for offset, entry in enumerate(group, start=1) if floor + offset != entry.entry_no]

        if moves:
            # Only entries whose number changes are touched. They are parked out of the way
            # first (see _PARK_OFFSET) so two entries never briefly share a number, then
            # given their final ones -- two statements each, not two per entry.
            parked = []
            for entry, _ in moves:
                parked.append(JournalEntry(pk=entry.pk, entry_no=entry.entry_no + _PARK_OFFSET))
            JournalEntry.objects.bulk_update(parked, ["entry_no"], batch_size=500)
            final = [JournalEntry(pk=entry.pk, entry_no=number) for entry, number in moves]
            JournalEntry.objects.bulk_update(final, ["entry_no"], batch_size=500)
            EntryChange.objects.bulk_create(
                [
                    EntryChange(
                        firm_id=client.firm_id, client=client, entry_id=entry.pk,
                        voucher_type=voucher_type, entry_no=number, entry_date=entry.entry_date,
                        action=ChangeAction.RENUMBERED,
                        before={"entry_no": entry.entry_no}, after={"entry_no": number},
                        note="Renumbered at sign-off so voucher numbers are contiguous.",
                        actor=actor,
                    )
                    for entry, number in moves
                ],
                batch_size=500,
            )
            changed += len(moves)
        VoucherSequence.objects.filter(
            firm_id=client.firm_id, client=client, financial_year=year, voucher_type=voucher_type
        ).update(next_number=floor + len(group) + 1)
    return changed


@transaction.atomic
def reopen(client, membership, *, note: str) -> BooksEvent:
    """Undo the latest sign-off, so the books can be changed again.

    Rare and deliberate: it needs a senior who may sign this client off and a
    reason, and it is written to the review history like everything else. The
    date goes back to what it was before the last sign-off.
    """
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    if not (note or "").strip():
        raise BooksError("A reason is required to reopen signed-off books.")

    current = status(client)
    if not current.is_locked:
        raise BooksError("Nothing is signed off, so there is nothing to reopen.")

    # Replay the history to find what the date was before the latest sign-off.
    # Counting sign-offs against reopens is wrong once a reopen has been
    # followed by a fresh sign-off; a stack is right however they interleave.
    stack: list[datetime.date] = []
    for event in BooksEvent.objects.filter(
        firm_id=client.firm_id, client=client, action__in=[BooksAction.SIGNED_OFF, BooksAction.REOPENED]
    ).order_by("created_at", "id"):
        if event.action == BooksAction.SIGNED_OFF:
            stack.append(event.through_date)
        elif stack:
            stack.pop()
    restore = stack[-2] if len(stack) >= 2 else None

    with connection.cursor() as cursor:
        # Declared for this transaction only: the client-row guard refuses to move
        # the date backwards unless the transaction says a reopen is intended.
        cursor.execute("SELECT set_config('app.allow_reopen', 'on', true)")
    Client.objects.filter(pk=client.pk).update(signed_off_through=restore)
    client.signed_off_through = restore
    return _event(client, BooksAction.REOPENED, actor=membership.user, through=restore, note=note)
