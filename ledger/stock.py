"""Opening stock and count adjustments: the stock movements that no invoice carries."""

from __future__ import annotations

import datetime
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
    note: str = "", membership,
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
        created_by=membership.user,
    )


@transaction.atomic
def remove(row: StockEntry, *, membership) -> None:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, row.client)
    through = editing.locked_through(row.client_id)
    if through is not None and row.entry_date <= through:
        raise StockError(f"The books are sealed through {through:%d-%m-%Y}, so this entry cannot be removed.")
    row.delete()
