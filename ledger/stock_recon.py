"""Does the stock register agree with the books, the bills and the item list?

The register (``ledger.inventory``) is worked out from invoice lines and stock entries; the books are the journal. Nothing forces
the two to agree, so this reads both and says where they part, in words a person can act on. It writes nothing.

Each check has a ``status``: ``ok`` (agrees), ``attention`` (a person should look) or ``info`` (a limit worth knowing).
"""

from __future__ import annotations

import datetime

from classify.models import LedgerGroup
from ledger import inventory, nce
from ledger.models import StockItem
from ledger.reports import _balances


def _check(key: str, title: str, status: str, message: str, examples: list[str] | None = None) -> dict:
    return {"key": key, "title": title, "status": status, "message": message, "examples": examples or []}


def _rupees(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    whole, part = divmod(abs(paise), 100)
    text = f"{whole:,}"
    # Indian grouping: last three digits, then pairs.
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        text = ",".join(pairs + [tail])
    return f"{sign}₹{text}.{part:02d}"


def build(client, fy: int) -> dict:
    report = inventory.build(client, fy)
    rows, _footer = _balances(client, fy)
    ledgers_paise = sum(r.net_paise for r in rows if r.group == LedgerGroup.STOCK)
    # A closing stock entered for the year in the statement settings is what the statements use (the gap to the ledgers is
    # added to the profit); with none entered the statements use the ledgers.
    entered = nce.read_settings(client)["years"].get(str(fy), {}).get("closing_stock_paise")
    books_paise = ledgers_paise if entered is None else entered
    # What the register holds: items with stock on hand. A negative quantity carries no cost, so it adds nothing here.
    register_paise = sum(i.closing_value_paise for i in report.items if i.closing_qty > 0)
    checks: list[dict] = []

    gap = register_paise - books_paise
    if not report.items and not books_paise:
        checks.append(_check("value", "Stock value against the books", "ok", "No stock in the register and none in the books."))
    elif gap == 0:
        checks.append(_check("value", "Stock value against the books", "ok", f"The register's closing stock, {_rupees(register_paise)}, is what the statements use."))
    else:
        checks.append(
            _check(
                "value",
                "Stock value against the books",
                "attention",
                f"The register's closing stock is {_rupees(register_paise)}; the statements use {_rupees(books_paise)}. "
                f"The profit and the balance sheet are therefore {_rupees(abs(gap))} "
                f"{'lower' if gap > 0 else 'higher'} on stock than the register says. Use the register's figure as the year's closing stock, or correct the register.",
            )
        )

    negative = [f"{i.name} ({inventory_plain(i.closing_qty)} {i.unit})".strip() for i in report.items if i.closing_qty < 0]
    checks.append(
        _check("negative", "Stock sold before it was bought", "attention", f"{len(negative)} item(s) have gone below zero: a purchase is missing, or the name differs.", negative[:8])
        if negative
        else _check("negative", "Stock sold before it was bought", "ok", "No item has gone below zero.")
    )

    kept = list(StockItem.objects.filter(firm_id=client.firm_id, client=client))
    unlisted = [i.name for i in report.items if not any(inventory._same_item(i.name, k.name) for k in kept)]
    checks.append(
        _check("unlisted", "Items missing from the item list", "attention", f"{len(unlisted)} item(s) in the register are not on the Stock items list, so their unit, HSN, GST rate and reorder level are not kept.", unlisted[:8])
        if unlisted
        else _check("unlisted", "Items missing from the item list", "ok", "Every item in the register is on the Stock items list.")
    )

    unused = [k.name for k in kept if not any(inventory._same_item(i.name, k.name) for i in report.items)]
    if unused:
        checks.append(_check("unused", "Listed items with no stock movement", "info", f"{len(unused)} item(s) on the list have no movement up to this year's end.", unused[:8]))

    clash = []
    for item in report.items:
        match = next((k for k in kept if inventory._same_item(item.name, k.name)), None)
        if match and match.unit and item.unit and match.unit.strip().lower() != item.unit.strip().lower():
            clash.append(f"{item.name}: list says {match.unit}, invoices say {item.unit}")
    if clash:
        checks.append(_check("unit", "Unit differs from the invoices", "attention", f"{len(clash)} item(s) are kept in one unit and invoiced in another.", clash[:8]))

    if report.bills_left_out:
        checks.append(
            _check(
                "left_out",
                "Purchases and sales that move no stock",
                "attention",
                f"{report.bills_left_out} booked purchase(s) or sale(s) this year have no invoice file or no item lines, so the register leaves them out.",
                report.left_out_examples,
            )
        )
    else:
        checks.append(_check("left_out", "Purchases and sales that move no stock", "ok", "Every booked purchase and sale this year has item lines."))

    if report.lines_without_value:
        checks.append(_check("no_value", "Item lines with no amount", "attention", f"{report.lines_without_value} line(s) move stock but carry no amount, so they carry no value."))
    else:
        checks.append(_check("no_value", "Item lines with no amount", "ok", "Every item line carries an amount."))

    return {
        "fy": fy,
        "register_value_paise": register_paise,
        "books_value_paise": books_paise,
        "difference_paise": gap,
        "agrees": all(c["status"] != "attention" for c in checks),
        "checks": checks,
        "as_at": datetime.date(fy + 1, 3, 31).isoformat(),
    }


def inventory_plain(value) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
