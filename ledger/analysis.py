"""Reading the books by group and by month: what Tally's Group Summary and a ledger's Monthly Summary show.

``group_summary`` totals each group's ledgers for the year (opening, debit, credit, closing). ``ledger_monthly`` takes one ledger
through the twelve months: the debit and credit of each month and the balance after it, ending at the same closing figure the Trial
Balance shows for that ledger. Both read from the same balances as the Trial Balance, so they cannot disagree with it. They write nothing.
"""

from __future__ import annotations

import datetime

from django.db.models import Q, Sum

from classify.models import LedgerAccount, LedgerGroup
from core.fy import fy_bounds
from ledger.models import JournalLine
from ledger.reports import _balances

MONTHS = (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)


def _label(group: str) -> str:
    try:
        return LedgerGroup(group).label
    except ValueError:
        return str(group)


def group_summary(client, fy: int) -> dict:
    rows, _ = _balances(client, fy)
    groups: dict[str, dict] = {}
    for row in rows:
        g = groups.setdefault(
            row.group,
            {"group": row.group, "label": _label(row.group), "opening_paise": 0, "debit_paise": 0, "credit_paise": 0, "closing_paise": 0, "ledgers": []},
        )
        g["opening_paise"] += row.opening_paise
        g["debit_paise"] += row.debit_paise
        g["credit_paise"] += row.credit_paise
        g["closing_paise"] += row.net_paise
        g["ledgers"].append(
            {
                "ledger_id": str(row.ledger_id) if row.ledger_id else None, "name": row.name, "opening_paise": row.opening_paise,
                "debit_paise": row.debit_paise, "credit_paise": row.credit_paise, "closing_paise": row.net_paise,
            }
        )
    ordered = sorted(groups.values(), key=lambda g: g["label"])
    return {
        "fy": fy,
        "groups": ordered,
        "total_debit_paise": sum(g["debit_paise"] for g in ordered),
        "total_credit_paise": sum(g["credit_paise"] for g in ordered),
    }


def ledger_monthly(client, fy: int, ledger: LedgerAccount) -> dict:
    start, end = fy_bounds(fy)
    rows, _ = _balances(client, fy)
    balance = next((r for r in rows if r.ledger_id == ledger.pk), None)
    opening = balance.opening_paise if balance else 0
    by_month: dict[tuple[int, int], dict] = {}
    lines = JournalLine.objects.filter(
        firm_id=client.firm_id, entry__client=client, ledger_account=ledger, entry__entry_date__range=(start, end)
    ).values("entry__entry_date__year", "entry__entry_date__month").annotate(
        debit=Sum("amount_paise", filter=Q(direction="DR")), credit=Sum("amount_paise", filter=Q(direction="CR"))
    )
    for row in lines:
        by_month[(row["entry__entry_date__year"], row["entry__entry_date__month"])] = {"debit": row["debit"] or 0, "credit": row["credit"] or 0}
    months, running = [], opening
    for m in MONTHS:
        year = fy if m >= 4 else fy + 1
        got = by_month.get((year, m), {"debit": 0, "credit": 0})
        running += got["debit"] - got["credit"]
        months.append({"month": f"{year}-{m:02d}", "debit_paise": got["debit"], "credit_paise": got["credit"], "closing_paise": running})
    return {
        "fy": fy,
        "ledger": {"id": str(ledger.pk), "name": ledger.name, "group": ledger.group, "group_label": _label(ledger.group)},
        "opening_paise": opening,
        "months": months,
        "total_debit_paise": sum(m["debit_paise"] for m in months),
        "total_credit_paise": sum(m["credit_paise"] for m in months),
        "closing_paise": running,
    }


def month_start(month: str) -> datetime.date:
    year, mon = (int(p) for p in month.split("-"))
    return datetime.date(year, mon, 1)
