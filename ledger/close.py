"""Everything that stands between a client's books and sign-off, on one page.

The month-end close was spread across screens: rows waiting in Review, entries the assistant posted that nobody checked,
bank accounts that do not agree with their statements, parties whose ledgers disagree with their bills, invoices uploaded
and never booked. Each of those is a control, and sign-off should not happen while a control is open and nobody has said
why. This gathers them: the controls (``checks``), and every open item with whether it blocks and whether a person has
explained it.

Nothing is stored except the explanations. An item or check that has been fixed is simply no longer here, so the page is
right by construction. An explanation is a person's note against one item (``CloseAcknowledgement``); it does not make
the item go away, it lets sign-off go ahead with the reason on record. Only kinds where the books and a document or the
bank disagree block sign-off (``BLOCKING_KINDS``); the rest are listed so they are seen, not gated, because a client
without invoice-wise accounting would otherwise never close.
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from banking.models import BankAccount
from classify.models import LedgerGroup
from core.access import require_sign_off
from core.rbac import require_permission
from ledger import books, openitems
from ledger.models import CloseAcknowledgement, EntryMarker, JournalEntry, JournalLine
from ledger.reconciliation import NoStatementError, check_balance

#: Open items that stop sign-off until someone explains them: the books and a document or the bank disagree.
BLOCKING_KINDS = frozenset({"party_out_of_balance", "payment_unallocated", "payment_bypasses_bills", "invoice_unbooked"})


class CloseError(ValueError):
    """The request cannot be done as asked. The message says what to change."""


class UnexplainedItemsError(books.BooksError):
    """Open items that block sign-off have not been explained."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(
            f"{count} open item{'s' if count != 1 else ''} that block{'' if count != 1 else 's'} sign-off "
            f"{'have' if count != 1 else 'has'} not been fixed or explained. Fix {'them' if count != 1 else 'it'}, or "
            f"write why it can stand, on the close page."
        )


@dataclass(frozen=True)
class Check:
    name: str
    title: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class CloseItem:
    key: str
    item: openitems.OpenItem
    title: str
    blocking: bool
    #: The person's reason, when one has explained it.
    note: str = ""
    explained_by: str = ""

    @property
    def explained(self) -> bool:
        return bool(self.note)


@dataclass
class CloseReport:
    through: datetime.date | None
    checks: list[Check] = field(default_factory=list)
    items: list[CloseItem] = field(default_factory=list)

    @property
    def unexplained_blocking(self) -> int:
        return sum(1 for i in self.items if i.blocking and not i.explained)

    @property
    def ready(self) -> bool:
        return self.unexplained_blocking == 0 and all(c.ok for c in self.checks)


def item_key(item: openitems.OpenItem) -> str:
    """A stable name for one open item, so an explanation stays with it as long as it stays the same item."""
    if item.link:
        return f"{item.kind}|{item.link['type']}|{item.link['id']}"
    return f"{item.kind}|{hashlib.sha1(item.summary.encode()).hexdigest()[:16]}"  # noqa: S324 -- an identifier, not a secret


def close_report(client, *, through: datetime.date | None = None) -> CloseReport:
    """The controls and open items for ``client``, as at ``through`` (default: the latest entry)."""
    if through is None:
        through = (
            JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
            .order_by("-entry_date")
            .values_list("entry_date", flat=True)
            .first()
        )
    report = CloseReport(through=through)
    report.checks = _checks(client, through)

    titles = openitems.kinds()
    notes = {
        a.item_key: a
        for a in CloseAcknowledgement.objects.filter(firm_id=client.firm_id, client=client).select_related("acknowledged_by")
    }
    for item in openitems.open_items(client):
        key = item_key(item)
        ack = notes.get(key)
        report.items.append(
            CloseItem(
                key=key,
                item=item,
                title=titles.get(item.kind, item.kind),
                blocking=item.kind in BLOCKING_KINDS,
                note=ack.note if ack else "",
                explained_by=(ack.acknowledged_by.email if ack and ack.acknowledged_by else ""),
            )
        )
    return report


def _checks(client, through: datetime.date | None) -> list[Check]:
    checks: list[Check] = []
    waiting = books._waiting(client, through=through)
    checks.append(
        Check(
            "rows_posted",
            "Every bank row is placed and posted",
            waiting == 0,
            "" if waiting == 0 else f"{waiting} transaction{'s' if waiting != 1 else ''} still need a decision.",
        )
    )

    unchecked = JournalEntry.objects.filter(firm_id=client.firm_id, client=client).exclude(marker=EntryMarker.NONE)
    if through is not None:
        unchecked = unchecked.filter(entry_date__lte=through)
    count = unchecked.count()
    checks.append(
        Check(
            "assistant_entries_checked",
            "Entries the assistant posted are checked by a person",
            count == 0,
            "" if count == 0 else f"{count} entr{'y' if count == 1 else 'ies'} not yet marked as checked.",
        )
    )

    suspense = JournalLine.objects.filter(
        firm_id=client.firm_id, entry__client=client, ledger_account__group=LedgerGroup.SUSPENSE
    )
    if through is not None:
        suspense = suspense.filter(entry__entry_date__lte=through)
    parked = suspense.aggregate(total=Sum("signed_paise"))["total"] or 0
    checks.append(
        Check(
            "suspense_clear",
            "Nothing is left in Suspense",
            parked == 0,
            "" if parked == 0 else "The Suspense account has a balance; every entry in it should be placed in a real ledger.",
        )
    )

    if through is not None:
        for account in BankAccount.objects.filter(firm_id=client.firm_id, client=client):
            try:
                balance = check_balance(account, through)
            except NoStatementError:
                continue
            checks.append(
                Check(f"bank_{account.pk}", f"{account} agrees with its statement", balance.matches, "" if balance.matches else balance.explain())
            )
    return checks


@transaction.atomic
def explain(client, item_key_: str, note: str, *, membership) -> CloseAcknowledgement:
    """Record why one open item may stand. It stays listed; sign-off no longer waits on it.

    Only someone who may sign this client's books off can say an item may stand: the same rule as the sign-off itself.
    """
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    note = (note or "").strip()
    if len(note) < 5:
        raise CloseError("Say why this can stand, in a few words.")
    if item_key_ not in {item_key(i) for i in openitems.open_items(client)}:
        raise CloseError("That item is no longer open, so there is nothing to explain.")
    try:
        ack, _ = CloseAcknowledgement.objects.update_or_create(
            firm_id=client.firm_id,
            client=client,
            item_key=item_key_,
            defaults={"note": note[:500], "acknowledged_by": membership.user, "acknowledged_at": timezone.now()},
        )
    except IntegrityError as exc:  # two people explaining the same item at once
        raise CloseError("Someone explained that item a moment ago. Reload and check their reason.") from exc
    return ack


@transaction.atomic
def withdraw(client, item_key_: str, *, membership) -> None:
    require_permission(membership, "books.sign_off")
    require_sign_off(membership, client)
    CloseAcknowledgement.objects.filter(firm_id=client.firm_id, client=client, item_key=item_key_).delete()


def require_clear(client) -> None:
    """Refuse sign-off while an item that blocks it has been neither fixed nor explained."""
    count = sum(
        1
        for item in openitems.open_items(client)
        if item.kind in BLOCKING_KINDS
        and not CloseAcknowledgement.objects.filter(firm_id=client.firm_id, client=client, item_key=item_key(item)).exists()
    )
    if count:
        raise UnexplainedItemsError(count)
