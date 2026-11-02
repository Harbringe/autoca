"""Bringing a client's stock items in from Tally's stock-item export.

Each row is matched to the client's stock item of the same name (any case). A new name makes an item; one that exists is only filled in
where it is blank, so what a person typed is never overwritten. The opening quantity and value become opening stock dated the first
day of the financial year, unless the year already has opening stock for that item or the books are sealed past that day. Run it twice and
the second run changes nothing. With ``apply=False`` the same rows are worked out and nothing is written, which is the preview.
"""

from __future__ import annotations

import datetime

from django.db import transaction

from ledger import editing, stock
from ledger.audit import ITEM_FIELDS, record_master_change, snapshot
from ledger.models import StockEntry, StockEntryKind, StockItem
from ledger.tally_stock import StockRow

NOTE = "Opening balance from Tally"


def run(client, rows: list[StockRow], fy: int, *, apply: bool, membership) -> dict:
    start = datetime.date(fy, 4, 1)
    through = editing.locked_through(client.pk)
    sealed = through is not None and start <= through
    counts = {"new": 0, "filled": 0, "same": 0, "opening_added": 0, "opening_skipped": 0}
    out = []
    with transaction.atomic():
        for row in rows:
            item = StockItem.objects.filter(firm_id=client.firm_id, client=client, name__iexact=row.name).first()
            result = {"name": row.name, "unit": row.unit, "opening_qty": format(row.opening_qty.normalize(), "f"), "opening_value_paise": row.opening_value_paise, "reason": ""}
            result["item"] = _item(client, item, row, apply, membership)
            counts[{"new": "new", "fill": "filled", "same": "same"}[result["item"]]] += 1
            if row.opening_qty <= 0:
                result["opening"] = "none"
            elif sealed:
                result["opening"] = "sealed"
                result["reason"] = f"The books are sealed through {through:%d-%m-%Y}, so opening stock cannot be dated {start:%d-%m-%Y}."
            elif StockEntry.objects.filter(firm_id=client.firm_id, client=client, kind=StockEntryKind.OPENING, entry_date=start, name__iexact=row.name).exists():
                result["opening"] = "exists"
                result["reason"] = "This year already has opening stock for this item."
            else:
                result["opening"] = "add"
                if apply:
                    stock.record(
                        client, kind=StockEntryKind.OPENING, entry_date=start, direction="IN", name=row.name, unit=row.unit,
                        quantity=row.opening_qty, value_paise=row.opening_value_paise, note=NOTE, membership=membership,
                    )
            if result["opening"] == "add":
                counts["opening_added"] += 1
            elif result["opening"] in ("sealed", "exists"):
                counts["opening_skipped"] += 1
            out.append(result)
        if not apply:
            transaction.set_rollback(True)
    return {"applied": apply, "rows": out, "counts": counts}


def _item(client, item, row: StockRow, apply: bool, membership) -> str:
    """``new`` (made), ``fill`` (blanks filled in) or ``same`` (nothing to add)."""
    if item is None:
        if apply:
            made = StockItem.objects.create(
                firm_id=client.firm_id, client=client, name=row.name, unit=row.unit, hsn_sac=row.hsn_sac, gst_rate=row.gst_rate
            )
            record_master_change(client, "ITEM", made.pk, "CREATED", label=f"Stock item: {made.name}", before={}, after=snapshot(made, ITEM_FIELDS), actor=membership.user)
        return "new"
    changes = {}
    if row.unit and not item.unit:
        changes["unit"] = row.unit
    if row.hsn_sac and not item.hsn_sac:
        changes["hsn_sac"] = row.hsn_sac
    if row.gst_rate is not None and item.gst_rate is None:
        changes["gst_rate"] = row.gst_rate
    if not changes:
        return "same"
    if apply:
        before = snapshot(item, ITEM_FIELDS)
        for field, value in changes.items():
            setattr(item, field, value)
        item.save(update_fields=list(changes))
        record_master_change(client, "ITEM", item.pk, "EDITED", label=f"Stock item: {item.name}", before=before, after=snapshot(item, ITEM_FIELDS), actor=membership.user)
    return "fill"
