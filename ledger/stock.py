"""Opening stock, count adjustments, physical counts and transfers between godowns: the stock movements that no invoice carries."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.access import require_posting_rights
from core.rbac import require_permission
from ledger import editing
from ledger.models import StockEntry, StockEntryKind


class StockError(ValueError):
    """The stock entry cannot be recorded. The message says what to change."""


@transaction.atomic
def record(
    client, *, kind: str, entry_date: datetime.date, direction: str, name: str, unit: str, quantity, value_paise: int,
    note: str = "", membership, godown=None,
) -> StockEntry:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    name = " ".join(str(name or "").split())
    if not name:
        raise StockError("Name the item.")
    try:
        quantity = Decimal(str(quantity))
    except InvalidOperation:
        raise StockError("The quantity is not a number.") from None
    if quantity <= 0:
        raise StockError("The quantity must be more than zero.")
    if value_paise < 0:
        raise StockError("The value cannot be negative.")
    if godown is not None and godown.client_id != client.pk:
        raise StockError("That godown belongs to another client.")
    if kind == StockEntryKind.TRANSFER:
        raise StockError("Use a stock transfer to move stock between godowns.")
    if kind == StockEntryKind.PRODUCTION:
        raise StockError("Use a production run to make finished goods from components.")
    if kind == StockEntryKind.OPENING:
        direction = "IN"
    elif direction not in ("IN", "OUT"):
        raise StockError("An adjustment is stock in or stock out.")
    through = editing.locked_through(client.pk)
    if through is not None and entry_date <= through:
        raise StockError(f"The books are sealed through {through:%d-%m-%Y}; date this after that.")
    return StockEntry.objects.create(
        firm_id=client.firm_id, client=client, kind=kind, entry_date=entry_date, direction=direction, name=name[:200],
        unit=(unit or "").strip()[:16], quantity=quantity, value_paise=value_paise, note=(note or "").strip()[:300],
        created_by=membership.user, godown=godown,
    )


def _clean_quantity(quantity) -> Decimal:
    try:
        quantity = Decimal(str(quantity))
    except InvalidOperation:
        raise StockError("The quantity is not a number.") from None
    if quantity <= 0:
        raise StockError("The quantity must be more than zero.")
    return quantity


def _check_open(client, entry_date: datetime.date) -> None:
    through = editing.locked_through(client.pk)
    if through is not None and entry_date <= through:
        raise StockError(f"The books are sealed through {through:%d-%m-%Y}; date this after that.")


@transaction.atomic
def transfer(
    client, *, entry_date: datetime.date, name: str, unit: str, quantity, from_godown, to_godown, note: str = "", membership,
) -> list[StockEntry]:
    """Move stock from one godown to another (``None`` is the main location): an out of one and an in to the other, sharing an id."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    name = " ".join(str(name or "").split())
    if not name:
        raise StockError("Name the item.")
    quantity = _clean_quantity(quantity)
    if (from_godown.pk if from_godown else None) == (to_godown.pk if to_godown else None):
        raise StockError("Choose two different places: stock is moved from one godown to another.")
    for godown in (from_godown, to_godown):
        if godown is not None and godown.client_id != client.pk:
            raise StockError("That godown belongs to another client.")
    _check_open(client, entry_date)
    shared = uuid.uuid4()
    made = []
    for direction, godown in ("OUT", from_godown), ("IN", to_godown):
        made.append(
            StockEntry.objects.create(
                firm_id=client.firm_id, client=client, kind=StockEntryKind.TRANSFER, entry_date=entry_date, direction=direction,
                name=name[:200], unit=(unit or "").strip()[:16], quantity=quantity, value_paise=0, note=(note or "").strip()[:300],
                created_by=membership.user, godown=godown, transfer=shared,
            )
        )
    return made


@transaction.atomic
def count(
    client, *, entry_date: datetime.date, name: str, unit: str, counted_quantity, godown=None, note: str = "", membership,
) -> dict:
    """A physical count: what was found against what the books say. A difference is booked as a stock adjustment (a shortage out,
    a surplus in at the average cost); no difference books nothing."""
    from ledger import inventory

    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    name = " ".join(str(name or "").split())
    if not name:
        raise StockError("Name the item.")
    try:
        counted = Decimal(str(counted_quantity))
    except InvalidOperation:
        raise StockError("The counted quantity is not a number.") from None
    if counted < 0:
        raise StockError("The counted quantity cannot be negative.")
    if godown is not None and godown.client_id != client.pk:
        raise StockError("That godown belongs to another client.")
    _check_open(client, entry_date)
    where = str(godown.pk) if godown else ("none" if client.godowns.exists() else None)
    book, _value = inventory.book_quantity(client, name, entry_date, where)
    difference = counted - book
    result = {"book_quantity": book, "counted_quantity": counted, "difference": difference, "entry": None}
    if difference == 0:
        return result
    _qty, whole_value = inventory.book_quantity(client, name, entry_date, None)
    whole_qty = _qty
    average = Decimal(whole_value) / whole_qty if whole_qty > 0 else Decimal(0)
    surplus = difference > 0
    value = int((average * abs(difference)).quantize(Decimal(1))) if surplus else 0
    reason = "Physical count" + (f": {note.strip()}" if note and note.strip() else "")
    result["entry"] = record(
        client, kind=StockEntryKind.ADJUSTMENT, entry_date=entry_date, direction="IN" if surplus else "OUT", name=name, unit=unit,
        quantity=abs(difference), value_paise=value, note=reason, membership=membership, godown=godown,
    )
    return result


@transaction.atomic
def remove(row: StockEntry, *, membership) -> None:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, row.client)
    through = editing.locked_through(row.client_id)
    if through is not None and row.entry_date <= through:
        raise StockError(f"The books are sealed through {through:%d-%m-%Y}, so this entry cannot be removed.")
    if row.transfer:
        StockEntry.objects.filter(firm_id=row.firm_id, client=row.client, transfer=row.transfer).delete()
        return
    if row.production:
        StockEntry.objects.filter(firm_id=row.firm_id, client=row.client, production=row.production).delete()
        return
    row.delete()
