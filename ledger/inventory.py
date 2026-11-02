"""Stock by item, month by month: what came in, what went out, what is left. The shape of Tally's Stock Item Monthly Summary.

AutoCA books vouchers, not stock, so the movements are taken from the lines of the invoices behind the booked bills: a purchase
line is stock coming in, a sale line is stock going out. A line a person confirmed counts the same as one the reader printed;
a bill with no invoice file, or no lines on it, has no movement here and is counted so the report says how much it leaves out.

``summarise`` is arithmetic only. ``movements`` (below) reads the lines from the books.

The closing value is at weighted-average cost, which is how a trader values stock that is bought and sold in lots:

* a purchase raises the quantity and the value by what it cost;
* a sale lowers the quantity, and the value by the quantity at the average cost so far;
* a quantity that goes negative (sold before the purchase was entered) is shown as it is, not hidden, and carries no cost,
  so a missing purchase is visible instead of netting away.

The opening position is whatever the earlier financial years' lines and stock entries come to. Opening stock, and corrections
found at a physical count, are recorded as stock entries (``ledger.stock``) since no invoice carries them.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal

from ledger.item_memory import similar

IN, OUT = "IN", "OUT"


@dataclass(frozen=True)
class Movement:
    date: datetime.date
    direction: str  # IN or OUT
    name: str
    unit: str
    quantity: Decimal
    value_paise: int
    #: Where it came from, in words a person knows: "Sales INV-9 · Sunrise Traders", "Opening stock".
    source: str = ""
    #: Which godown it is in (an id); None is the main location.
    godown: str | None = None
    #: One leg of a transfer between godowns. It changes where stock is, not how much there is, so the whole-business
    #: figures leave it out.
    transfer: bool = False


@dataclass
class MasterLevel:
    """A stock item's reorder level from the item master, to be matched to the report's items by name."""

    name: str
    reorder_level: Decimal | None


@dataclass
class MonthRow:
    month: str  # YYYY-MM
    in_qty: Decimal = Decimal(0)
    in_value_paise: int = 0
    out_qty: Decimal = Decimal(0)
    out_value_paise: int = 0
    closing_qty: Decimal = Decimal(0)
    closing_value_paise: int = 0


@dataclass
class ItemSummary:
    name: str
    unit: str
    opening_qty: Decimal
    opening_value_paise: int
    months: list[MonthRow] = field(default_factory=list)
    #: The year's movements, oldest first; the ones before it are in the opening balance.
    movements: list[Movement] = field(default_factory=list)
    reorder_level: Decimal | None = None
    below_reorder: bool = False

    @property
    def closing_qty(self) -> Decimal:
        return self.months[-1].closing_qty if self.months else self.opening_qty

    @property
    def closing_value_paise(self) -> int:
        return self.months[-1].closing_value_paise if self.months else self.opening_value_paise


def parse_quantity(text: str | None) -> Decimal | None:
    """A quantity as printed (``60``, ``6.0``, ``2,000 kg``): the number in it, or None."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(text or ""))
    if not match:
        return None
    try:
        value = Decimal(match.group(0).replace(",", ""))
    except ArithmeticError:
        return None
    return value if value > 0 else None


def fy_months(fy: int) -> list[str]:
    """April of ``fy`` to March of ``fy + 1``, as YYYY-MM."""
    return [f"{fy if m >= 4 else fy + 1}-{m:02d}" for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)]


def _same_item(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower() or similar(a, b)


def summarise(movements: list[Movement], fy: int) -> list[ItemSummary]:
    """One summary per item for the financial year starting in April of ``fy``; movements before it make the opening."""
    start = datetime.date(fy, 4, 1)
    end = datetime.date(fy + 1, 3, 31)
    groups: list[tuple[str, list[Movement]]] = []
    for movement in sorted(movements, key=lambda m: (m.date, m.direction != IN)):
        if movement.date > end:
            continue
        for key, group in groups:
            if _same_item(key, movement.name):
                group.append(movement)
                break
        else:
            groups.append((movement.name, [movement]))

    out: list[ItemSummary] = []
    months = fy_months(fy)
    for name, group in groups:
        qty, value = Decimal(0), 0  # stock on hand and what it is carried at
        before = [m for m in group if m.date < start]
        for movement in before:
            qty, value = _apply(qty, value, movement)
        summary = ItemSummary(name=name, unit=next((m.unit for m in group if m.unit), ""), opening_qty=qty, opening_value_paise=value)
        summary.movements = [m for m in group if m.date >= start]
        rows = {month: MonthRow(month) for month in months}
        for movement in (m for m in group if m.date >= start):
            row = rows[f"{movement.date:%Y-%m}"]
            if movement.direction == IN:
                row.in_qty += movement.quantity
                row.in_value_paise += movement.value_paise
            else:
                row.out_qty += movement.quantity
                row.out_value_paise += movement.value_paise
            qty, value = _apply(qty, value, movement)
            row.closing_qty, row.closing_value_paise = qty, value
        carried_qty, carried_value = summary.opening_qty, summary.opening_value_paise
        for month in months:
            row = rows[month]
            if row.in_qty == 0 and row.out_qty == 0:
                row.closing_qty, row.closing_value_paise = carried_qty, carried_value
            else:
                carried_qty, carried_value = row.closing_qty, row.closing_value_paise
            summary.months.append(row)
        if any(m.in_qty or m.out_qty for m in summary.months) or summary.opening_qty:
            out.append(summary)
    return sorted(out, key=lambda s: s.name.lower())


def apply_reorder_levels(items: list[ItemSummary], masters: list[MasterLevel]) -> None:
    """Give each item the reorder level of the master record it is the same product as; flag the ones at or below it."""
    for item in items:
        master = next((m for m in masters if _same_item(m.name, item.name)), None)
        if master is None or master.reorder_level is None:
            continue
        item.reorder_level = master.reorder_level
        item.below_reorder = item.closing_qty <= master.reorder_level


def _apply(qty: Decimal, value: int, movement: Movement) -> tuple[Decimal, int]:
    if movement.direction == IN:
        return qty + movement.quantity, value + movement.value_paise
    average = Decimal(value) / qty if qty > 0 else Decimal(0)  # with nothing on hand there is no cost to take out
    cost = int((average * movement.quantity).quantize(Decimal(1)))
    return qty - movement.quantity, value - cost


# ---------------------------------------------------------------------------
# From the books
# ---------------------------------------------------------------------------


@dataclass
class InventoryReport:
    fy: int
    items: list[ItemSummary]
    bills_counted: int
    #: Purchases and sales in the books that add nothing here: no invoice file, or no lines with a quantity on it.
    bills_left_out: int
    left_out_examples: list[str]
    #: Lines with a quantity but no amount: they move stock and carry no value.
    lines_without_value: int
    #: A godown's figures are quantities: a transfer carries no cost, so a value would be wrong. Shown as such.
    quantities_only: bool = False


def _in_godown(movements: list[Movement], godown: str | None) -> list[Movement]:
    """``None`` is the whole business (transfers cancel out and are left out); ``"none"`` the main location; else one godown by id."""
    if godown is None:
        return [m for m in movements if not m.transfer]
    if godown == "none":
        return [m for m in movements if m.godown is None]
    return [m for m in movements if m.godown == godown]


def _collect(client, end: datetime.date, since: datetime.date):
    """Every movement up to ``end``: invoice lines, then the stock entries. ``since`` is where the report year starts, for counting
    the purchases and sales that add nothing to it."""
    from ledger.invoice_intake import fields_of
    from ledger.models import Bill, BillKind, InvoiceReading

    bills = list(
        Bill.objects.filter(firm_id=client.firm_id, client=client, kind__in=(BillKind.PURCHASE, BillKind.SALES), bill_date__lte=end)
        .select_related("party")
        .order_by("bill_date", "reference")
    )
    readings = {
        r.bill_id: r
        for r in InvoiceReading.objects.filter(firm_id=client.firm_id, client=client, bill_id__in=[b.pk for b in bills])
    }
    # A bill that came in with a Tally import has its items in the stock register already, so it is not 'left out'.
    from ledger.models import TallyVoucher

    imported = set(TallyVoucher.objects.filter(firm_id=client.firm_id, client=client).values_list('entry_id', flat=True))
    movements: list[Movement] = []
    counted = left_out = no_value = 0
    examples: list[str] = []
    for bill in bills:
        if bill.entry_id in imported:
            counted += 1
            continue
        reading = readings.get(bill.pk)
        lines = (fields_of(reading).get("items") or []) if reading is not None else []
        found = 0
        for line in lines:
            quantity = parse_quantity(line.get("quantity"))
            name = str(line.get("description") or "").strip()
            if quantity is None or not name:
                continue
            amount = line.get("amount_paise")
            if amount is None:
                no_value += 1
            movements.append(
                Movement(
                    date=bill.bill_date,
                    direction=IN if bill.kind == BillKind.PURCHASE else OUT,
                    name=name,
                    unit=str(line.get("unit") or "").strip(),
                    quantity=quantity,
                    value_paise=int(amount or 0),
                    source=f"{'Purchase' if bill.kind == BillKind.PURCHASE else 'Sales'} {bill.reference} · {bill.party.canonical_name}",
                )
            )
            found += 1
        if found:
            counted += 1
        elif bill.bill_date >= since:
            left_out += 1
            if len(examples) < 5:
                examples.append(f"{bill.reference} ({bill.party.canonical_name})")
    from ledger.models import StockEntry, StockEntryKind

    rows = list(StockEntry.objects.filter(firm_id=client.firm_id, client=client, entry_date__lte=end).select_related("godown"))
    # The two halves of a transfer name each other's godown: "Stock transfer from Shop" / "Stock transfer to Yard".
    where: dict = {}
    for row in rows:
        if row.transfer:
            where.setdefault(row.transfer, {})[row.direction] = row.godown.name if row.godown_id else "Main location"
    for row in rows:
        if row.transfer:
            other = where.get(row.transfer, {}).get("OUT" if row.direction == "IN" else "IN", "")
            source = f"Stock transfer {'from' if row.direction == 'IN' else 'to'} {other}".strip()
        else:
            source = row.get_kind_display() + (f" · {row.note}" if row.note else "")
        movements.append(
            Movement(
                date=row.entry_date, direction=row.direction, name=row.name, unit=row.unit,
                quantity=row.quantity, value_paise=row.value_paise, source=source,
                godown=str(row.godown_id) if row.godown_id else None, transfer=row.kind == StockEntryKind.TRANSFER,
            )
        )
    return _canonical(client, movements), counted, left_out, examples, no_value


def _canonical(client, movements: list[Movement]) -> list[Movement]:
    """A line named by one of an item's other names counts as that item, however different the spelling."""
    from dataclasses import replace

    from ledger.models import StockItem

    by_alias = {}
    for item in StockItem.objects.filter(firm_id=client.firm_id, client=client):
        for alias in item.aliases or []:
            by_alias[str(alias).strip().lower()] = item.name
    if not by_alias:
        return movements
    return [replace(m, name=by_alias[m.name.strip().lower()]) if m.name.strip().lower() in by_alias else m for m in movements]


def book_quantity(client, name: str, as_at: datetime.date, godown: str | None = None) -> tuple[Decimal, int]:
    """What the books say is on hand of ``name`` at the end of ``as_at``, and what it is carried at; for one godown when named
    (``"none"`` is the main location), else the whole business."""
    movements = _in_godown(_collect(client, as_at, as_at)[0], godown)
    qty, value = Decimal(0), 0
    for movement in sorted((m for m in movements if _same_item(m.name, name)), key=lambda m: (m.date, m.direction != IN)):
        qty, value = _apply(qty, value, movement)
    return qty, value


def build(client, fy: int, godown: str | None = None) -> InventoryReport:
    """The year's stock summary for ``client``, from the invoice lines behind its booked purchases and sales and the stock entries.
    ``godown`` limits it to one godown (``"none"``: the main location)."""
    end = datetime.date(fy + 1, 3, 31)
    movements, counted, left_out, examples, no_value = _collect(client, end, datetime.date(fy, 4, 1))
    movements = _in_godown(movements, godown)
    from ledger.models import StockItem

    items = summarise(movements, fy)
    apply_reorder_levels(
        items,
        [MasterLevel(name=i.name, reorder_level=i.reorder_level) for i in StockItem.objects.filter(firm_id=client.firm_id, client=client)],
    )
    return InventoryReport(
        fy=fy,
        quantities_only=godown is not None,
        items=items,
        bills_counted=counted,
        bills_left_out=left_out,
        left_out_examples=examples,
        lines_without_value=no_value,
    )
