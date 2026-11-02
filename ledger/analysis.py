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
from ledger.models import Budget, CostCentre, CostCentreTag, Direction, JournalLine
from ledger.reports import INCOME_GROUPS, PROFIT_AND_LOSS_GROUPS, _balances

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


def _period(fy: int, m: int) -> datetime.date:
    return datetime.date(fy if m >= 4 else fy + 1, m, 1)


def budgets_for(client, fy: int) -> list[dict]:
    """Each budgeted ledger with its twelve months, in the order of the year; a month with no figure is None."""
    start, end = fy_bounds(fy)
    rows = Budget.objects.filter(firm_id=client.firm_id, client=client, period__range=(start, end)).select_related("ledger")
    by_ledger: dict = {}
    for row in rows:
        entry = by_ledger.setdefault(row.ledger_id, {"ledger_id": str(row.ledger_id), "ledger": row.ledger.name, "group": row.ledger.group, "months": {}})
        entry["months"][row.period.strftime("%Y-%m")] = row.amount_paise
    out = []
    for entry in sorted(by_ledger.values(), key=lambda e: e["ledger"]):
        months = [{"month": _period(fy, m).strftime("%Y-%m"), "amount_paise": entry["months"].get(_period(fy, m).strftime("%Y-%m"))} for m in MONTHS]
        out.append({**{k: entry[k] for k in ("ledger_id", "ledger", "group")}, "months": months, "total_paise": sum(m["amount_paise"] or 0 for m in months)})
    return out


def budget_variance(client, fy: int, *, through: str | None = None) -> dict:
    """Budget against what the books show, month by month, for each budgeted ledger.

    Actual is the month's movement in the ledger's natural direction: credits less debits for income, debits less credits for everything
    else. Variance is actual less budget; for an expense, a positive variance is overspending and for income it is earning more than planned.
    ``through`` (YYYY-MM) limits the year-to-date total to the months up to and including it.
    """
    start, end = fy_bounds(fy)
    budgets = budgets_for(client, fy)
    ids = [b["ledger_id"] for b in budgets]
    moved: dict = {}
    if ids:
        lines = JournalLine.objects.filter(
            firm_id=client.firm_id, entry__client=client, ledger_account_id__in=ids, entry__entry_date__range=(start, end)
        ).values("ledger_account_id", "entry__entry_date__year", "entry__entry_date__month").annotate(
            debit=Sum("amount_paise", filter=Q(direction="DR")), credit=Sum("amount_paise", filter=Q(direction="CR"))
        )
        for row in lines:
            key = (str(row["ledger_account_id"]), f"{row['entry__entry_date__year']}-{row['entry__entry_date__month']:02d}")
            moved[key] = (row["debit"] or 0, row["credit"] or 0)
    result = []
    for b in budgets:
        income = b["group"] in INCOME_GROUPS
        months, ytd_budget, ytd_actual = [], 0, 0
        for m in b["months"]:
            debit, credit = moved.get((b["ledger_id"], m["month"]), (0, 0))
            actual = (credit - debit) if income else (debit - credit)
            budget = m["amount_paise"]
            months.append({"month": m["month"], "budget_paise": budget, "actual_paise": actual, "variance_paise": actual - (budget or 0)})
            if through is None or m["month"] <= through:
                ytd_budget += budget or 0
                ytd_actual += actual
        result.append(
            {
                "ledger_id": b["ledger_id"], "ledger": b["ledger"], "is_income": income, "months": months,
                "budget_paise": ytd_budget, "actual_paise": ytd_actual, "variance_paise": ytd_actual - ytd_budget,
            }
        )
    return {"fy": fy, "through": through, "ledgers": result}


def cost_centre_report(client, fy: int) -> dict:
    """Income and expense by cost centre for the year, from the journal lines tagged to them, and what is not tagged yet."""
    start, end = fy_bounds(fy)
    tags = CostCentreTag.objects.filter(
        firm_id=client.firm_id, client=client, line__entry__entry_date__range=(start, end)
    ).select_related("cost_centre", "line__ledger_account")
    centres: dict = {
        c.pk: {"id": str(c.pk), "name": c.name, "income_paise": 0, "expense_paise": 0, "ledgers": {}}
        for c in CostCentre.objects.filter(firm_id=client.firm_id, client=client)
    }
    tagged: dict = {}
    for tag in tags:
        line = tag.line
        if line.ledger_account.group not in PROFIT_AND_LOSS_GROUPS:
            continue
        income = line.ledger_account.group in INCOME_GROUPS
        signed = tag.amount_paise if (line.direction == Direction.CREDIT) == income else -tag.amount_paise
        c = centres[tag.cost_centre_id]
        c["income_paise" if income else "expense_paise"] += signed
        row = c["ledgers"].setdefault(line.ledger_account.name, {"ledger": line.ledger_account.name, "is_income": income, "amount_paise": 0})
        row["amount_paise"] += signed
        tagged[line.pk] = tagged.get(line.pk, 0) + tag.amount_paise
    untagged_income = untagged_expense = 0
    pl_lines = JournalLine.objects.filter(
        firm_id=client.firm_id, entry__client=client, entry__entry_date__range=(start, end), ledger_account__group__in=PROFIT_AND_LOSS_GROUPS
    ).select_related("ledger_account")
    for line in pl_lines:
        left = line.amount_paise - tagged.get(line.pk, 0)
        income = line.ledger_account.group in INCOME_GROUPS
        signed = left if (line.direction == Direction.CREDIT) == income else -left
        if income:
            untagged_income += signed
        else:
            untagged_expense += signed
    out = []
    for c in sorted(centres.values(), key=lambda c: c["name"]):
        c["ledgers"] = sorted(c["ledgers"].values(), key=lambda r: r["ledger"])
        c["net_paise"] = c["income_paise"] - c["expense_paise"]
        out.append(c)
    return {
        "fy": fy, "centres": out, "unallocated_income_paise": untagged_income, "unallocated_expense_paise": untagged_expense,
    }
