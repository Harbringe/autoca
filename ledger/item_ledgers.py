"""Invoice items as stock items with their own purchase and sales ledgers.

A bill's heads are normally one general ledger ("Purchases"). With item-wise booking each line of the invoice is posted to a
ledger of its own ("Purchases - Portland Cement"), so the profit and loss reads item by item, and each product is kept as a
stock item the register can be read against.

Only done when it is exact: every line must carry an amount and the lines must add up to the taxable value, or the request is
refused and nothing is booked. Taxes, TDS and the party's account are untouched; only how the taxable value is spread changes.
"""

from __future__ import annotations

from classify.models import LedgerAccount, LedgerGroup, LedgerStatus
from core.names import normalise
from ledger.billing import BillingError
from ledger.item_memory import similar
from ledger.models import BillKind, StockItem

#: Printed lines are each rounded, so they can miss the invoice's taxable value by a paisa or two. A miss of up to this many paise is
#: put on the largest line; a bigger one is a misread line, and the request is refused as before.
LINE_ROUNDING_PAISE = 5
#: Long enough that two products whose names differ only late do not land on one ledger (a ledger's name is at most 255).
LEDGER_NAME_LIMIT = 120

PREFIX = {BillKind.PURCHASE: "Purchases", BillKind.SALES: "Sales", BillKind.DEBIT_NOTE: "Purchases", BillKind.CREDIT_NOTE: "Sales"}
GROUP = {BillKind.PURCHASE: LedgerGroup.PURCHASE, BillKind.SALES: LedgerGroup.SALES}


def item_for(client, description: str, unit: str = "", hsn_sac: str = "") -> StockItem:
    name = normalise(description)[:150] or "Item"
    items = list(StockItem.objects.filter(firm_id=client.firm_id, client=client))
    found = next((i for i in items if i.name.lower() == name.lower()), None) or next((i for i in items if similar(i.name, name)), None)
    if found is None:
        found = StockItem.objects.create(firm_id=client.firm_id, client=client, name=name, unit=unit[:16], hsn_sac=hsn_sac[:8])
    return found


def ledger_for(client, item: StockItem, kind: str) -> LedgerAccount:
    side = "sales_ledger" if kind in (BillKind.SALES, BillKind.CREDIT_NOTE) else "purchase_ledger"
    existing = getattr(item, side)
    if existing is not None and existing.status == LedgerStatus.ACTIVE:
        return existing
    group = GROUP.get(BillKind.SALES if side == "sales_ledger" else BillKind.PURCHASE)
    name = f"{PREFIX[kind]} - {item.name}"[:LEDGER_NAME_LIMIT]
    ledger, _ = LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name=name,
        defaults={"group": group, "status": LedgerStatus.ACTIVE, "proposal_reason": "Opened for an invoice item."},
    )
    setattr(item, side, ledger)
    item.save(update_fields=[side])
    return ledger


def heads_from_items(client, kind: str, items: list[dict], taxable_paise: int) -> list[tuple]:
    """One head per product (lines of the same product are added together). Refuses unless the lines add up exactly."""
    if kind not in PREFIX:
        raise BillingError("Item-wise booking applies to purchases, sales and their notes.")
    lines = [i for i in items if (i.get("description") or "").strip()]
    if not lines:
        raise BillingError("Item-wise booking needs the invoice's lines.")
    if any(not i.get("amount_paise") or i["amount_paise"] <= 0 for i in lines):
        raise BillingError("Every line needs an amount for item-wise booking.")
    amounts = [i["amount_paise"] for i in lines]
    gap = taxable_paise - sum(amounts)
    if abs(gap) > LINE_ROUNDING_PAISE:
        raise BillingError("The lines do not add up to the taxable value, so they cannot be posted item by item.")
    if gap:
        # The invoice's own rounding: the largest line takes it, so the heads add to the taxable value exactly.
        amounts[amounts.index(max(amounts))] += gap
    by_ledger: dict = {}
    for line, amount in zip(lines, amounts, strict=True):
        item = item_for(client, line["description"], line.get("unit", ""), line.get("hsn_sac", ""))
        ledger = ledger_for(client, item, kind)
        by_ledger[ledger] = by_ledger.get(ledger, 0) + amount
    return list(by_ledger.items())
