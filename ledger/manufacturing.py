"""Making finished goods from components: a production run uses up the components and brings in the finished item.

A bill of materials says how much of each component goes into a batch of the finished item. A run of ``quantity`` of the finished item
takes each component out of stock at its weighted-average cost on that day and brings the finished item in at the total of those costs
plus any extra cost (labour, power) the run is given. The legs of a run share a ``production`` id, so removing one removes the run.
Components that are not there in the quantity needed stop the run, and the message names each.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from core.access import require_posting_rights
from core.rbac import require_permission
from ledger import inventory
from ledger.models import StockEntry, StockEntryKind
from ledger.stock import StockError, _check_open


def _qty(value, what: str) -> Decimal:
    try:
        q = Decimal(str(value))
    except InvalidOperation:
        raise StockError(f"{what} is not a number.") from None
    if q <= 0:
        raise StockError(f"{what} must be more than zero.")
    return q


def plan(client, bom, quantity, on: datetime.date, godown=None) -> dict:
    """What a run of ``quantity`` of the finished item would take, what is there, and what it would cost; nothing is written."""
    quantity = _qty(quantity, "The quantity")
    if godown is not None and godown.client_id != client.pk:
        raise StockError("That godown belongs to another client.")
    factor = quantity / bom.output_quantity
    where = str(godown.pk) if godown else ("none" if client.godowns.exists() else None)
    rows, short, total = [], [], 0
    for comp in bom.components:
        needed = (Decimal(str(comp["quantity"])) * factor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if needed <= 0:
            continue
        here, _ = inventory.book_quantity(client, comp["name"], on, where)
        whole, value = inventory.book_quantity(client, comp["name"], on, None)
        average = Decimal(value) / whole if whole > 0 else Decimal(0)
        cost = int((average * needed).quantize(Decimal(1)))
        ok = here >= needed
        rows.append({"name": comp["name"], "unit": comp.get("unit", ""), "needed": needed, "available": here, "cost_paise": cost, "enough": ok})
        total += cost
        if not ok:
            short.append(f"{comp['name']}: needs {needed.normalize():f}, has {max(here, Decimal(0)).normalize():f}")
    return {"quantity": quantity, "components": rows, "cost_paise": total, "short": short, "where": where}


@transaction.atomic
def produce(client, bom, *, quantity, entry_date: datetime.date, godown=None, extra_cost_paise: int = 0, note: str = "", membership) -> list[StockEntry]:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    if extra_cost_paise < 0:
        raise StockError("The extra cost cannot be negative.")
    _check_open(client, entry_date)
    worked = plan(client, bom, quantity, entry_date, godown)
    if worked["short"]:
        raise StockError("Not enough stock to make this: " + "; ".join(worked["short"]) + ".")
    shared = uuid.uuid4()
    label = f"Production of {worked['quantity'].normalize():f} {bom.name}" + (f": {note.strip()}" if note and note.strip() else "")
    made = []
    for row in worked["components"]:
        made.append(
            StockEntry.objects.create(
                firm_id=client.firm_id, client=client, kind=StockEntryKind.PRODUCTION, entry_date=entry_date, direction="OUT",
                name=row["name"][:200], unit=row["unit"][:16], quantity=row["needed"], value_paise=row["cost_paise"], note=label[:300],
                created_by=membership.user, godown=godown, production=shared,
            )
        )
    made.append(
        StockEntry.objects.create(
            firm_id=client.firm_id, client=client, kind=StockEntryKind.PRODUCTION, entry_date=entry_date, direction="IN",
            name=bom.name[:200], unit=bom.unit[:16], quantity=worked["quantity"], value_paise=worked["cost_paise"] + extra_cost_paise,
            note=label[:300], created_by=membership.user, godown=godown, production=shared,
        )
    )
    return made
