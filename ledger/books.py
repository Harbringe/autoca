"""Getting a client's books from a working draft to signed off.

The shape of the work, as a firm actually does it:

1. The AI fills the books from the statement. A CA works through them --
   removing what is wrong, correcting what is close -- while nothing is final.
2. When the CA is done they **request approval**.
3. A senior looks at the books as a whole -- the trial balance, the balance
   sheet -- and either **returns** them with a note or **signs off**.
4. Sign-off **locks** everything dated up to the date signed. From then on the
   database itself refuses to change it (``ledger.0008``).

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


class NothingRequestedError(BooksError):
    """A senior can only sign off books that somebody has submitted."""


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
    return BooksStatus(
        signed_off_through=through,
        review_pending=pending,
        requested_by=(last.actor.email if pending and last.actor else ""),
        requested_at=last.created_at if pending else None,
        returned_note=last.note if last is not None and last.action == BooksAction.RETURNED else "",
    )


def _waiting(client, *, through: datetime.date | None = None) -> int:
    """Rows not yet posted, optionally only those dated on or before ``through``."""
    rows = review_queue(client)
    if through is not None:
        rows = rows.filter(transaction__value_date__lte=through)
    return rows.count()


def _event(client, action, *, actor, through=None, note="") -> BooksEvent:
    return BooksEvent.objects.create(
        firm_id=client.firm_id, client=client, action=action,
        through_date=through, note=note[:1000], actor=actor,
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


@transaction.atomic
def sign_off(client, membership, *, through: datetime.date | None = None, note: str = "") -> BooksEvent:
    """A senior signs the books off, and they lock.

    ``through`` defaults to the date of the latest entry. Everything up to and
    including it is locked; entries dated later stay a working draft, so the
    next month's statement can be worked while this one is closed.
    """
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    if not status(client).review_pending:
        raise NothingRequestedError(
            "Nothing has been submitted for sign-off. A CA requests approval first."
        )

    previous = status(client).signed_off_through
    latest = (
        JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
        .order_by("-entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    if latest is None:
        raise BooksError("There are no entries to sign off.")
    through = through or latest
    if previous is not None and through <= previous:
        raise BooksError(f"The books are already signed off through {previous:%d-%m-%Y}.")

    waiting = _waiting(client, through=through)
    if waiting:
        # A row dated inside the period that is not posted can never be posted
        # once the period locks -- the database would refuse -- so it has to be
        # dealt with first, not left behind the lock.
        raise NotReadyError(waiting)

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
