"""The figures a firm and a client's books are looked at by: position, trend, what is owed, what is due.

Everything here is read from the books and the records beside them (the journal, bills, the close page, TDS), never stored,
so the dashboard cannot disagree with a report. Money is whole paise. Nothing is scored or ranked between people; what is
ranked is what needs attention, by how serious it is.

Two views:

* ``client_snapshot``: one client's financial position and trend for a financial year.
* ``portfolio``: every client the person may see, one row each, with what needs attention and what falls due soon.
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db.models import Sum

from banking.models import BankAccount
from core.fy import fy_bounds
from ledger import books, close, partyreports, tds
from ledger.models import JournalEntry, JournalLine
from ledger.overview import firm_overview
from ledger.reconciliation import ledger_balance
from ledger.reports import INCOME_GROUPS, PROFIT_AND_LOSS_GROUPS

#: Beyond this many clients the per-client detail (open items, reconciliation, ageing) is left out of the portfolio, so the
#: page stays quick for a very large firm; the stage and the next step still show for every client.
DETAIL_LIMIT = 60

GST_LEDGERS = (
    "Output CGST",
    "Output SGST",
    "Output IGST",
    "Output Cess",
    "Input CGST",
    "Input SGST",
    "Input IGST",
    "Input Cess",
)


def _month_key(day: datetime.date) -> str:
    return f"{day.year}-{day.month:02d}"


def _months(start: datetime.date, end: datetime.date) -> list[str]:
    out, year, month = [], start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def monthly_trend(client, year: int) -> list[dict]:
    """Income, expense and profit for each month of the financial year, from the journal."""
    start, end = fy_bounds(year)
    rows = (
        JournalLine.objects.filter(
            firm_id=client.firm_id,
            entry__client=client,
            entry__entry_date__gte=start,
            entry__entry_date__lte=end,
            ledger_account__group__in=PROFIT_AND_LOSS_GROUPS,
        )
        .values("entry__entry_date", "ledger_account__group")
        .annotate(total=Sum("signed_paise"))
    )
    income: dict[str, int] = defaultdict(int)
    expense: dict[str, int] = defaultdict(int)
    for row in rows:
        key = _month_key(row["entry__entry_date"])
        if row["ledger_account__group"] in INCOME_GROUPS:
            income[key] += -row["total"]  # a credit is negative; income is what was credited
        else:
            expense[key] += row["total"]
    return [
        {
            "month": m,
            "income_paise": income[m],
            "expense_paise": expense[m],
            "profit_paise": income[m] - expense[m],
        }
        for m in _months(start, end)
    ]


def top_expenses(client, year: int, limit: int = 5) -> list[dict]:
    start, end = fy_bounds(year)
    rows = (
        JournalLine.objects.filter(
            firm_id=client.firm_id,
            entry__client=client,
            entry__entry_date__gte=start,
            entry__entry_date__lte=end,
            ledger_account__group__in=PROFIT_AND_LOSS_GROUPS - INCOME_GROUPS,
        )
        .values("ledger_account__name")
        .annotate(total=Sum("signed_paise"))
        .order_by("-total")[:limit]
    )
    return [
        {"ledger": r["ledger_account__name"], "amount_paise": r["total"]}
        for r in rows
        if r["total"] > 0
    ]


def _ledger_sum(client, names, as_of: datetime.date) -> int:
    return (
        JournalLine.objects.filter(
            firm_id=client.firm_id,
            entry__client=client,
            ledger_account__name__in=names,
            entry__entry_date__lte=as_of,
        ).aggregate(total=Sum("signed_paise"))["total"]
        or 0
    )


def accounts(client, as_of: datetime.date) -> list[dict]:
    """Bank, card and loan balances as the books hold them. For a card or loan the figure is what is owed."""
    return [
        {
            "label": str(account),
            "kind": account.kind,
            "balance_paise": ledger_balance(account, as_of),
        }
        for account in BankAccount.objects.filter(
            firm_id=client.firm_id, client=client, is_active=True
        ).order_by("kind", "ledger_name")
    ]


def owed(client, as_of: datetime.date) -> dict:
    """What customers owe the client and what the client owes suppliers, with how much is over 90 days."""
    result = {}
    for side in (partyreports.RECEIVABLES, partyreports.PAYABLES):
        report = partyreports.outstanding(client, as_of, side)
        top = sorted(report.parties, key=lambda p: -abs(p.total_paise))[:3]
        result[side] = {
            "total_paise": report.total_paise,
            "over_90_paise": report.bucket_paise("Over 90"),
            "top": [
                {"name": p.party.canonical_name, "amount_paise": p.total_paise}
                for p in top
                if p.total_paise
            ],
        }
    return result


def client_snapshot(client, year: int, today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    start, end = fy_bounds(year)
    as_of = min(today, end)
    trend = monthly_trend(client, year)
    status = books.status(client)
    report = close.close_report(client)
    failing = [c.title for c in report.checks if not c.ok]
    gst_net = -_ledger_sum(
        client, GST_LEDGERS, as_of
    )  # credits (output) less debits (input): positive is payable
    tds_payable = -_ledger_sum(client, ["TDS Payable"], as_of)
    return {
        "financial_year": year,
        "as_of": as_of,
        "income_paise": sum(m["income_paise"] for m in trend),
        "expense_paise": sum(m["expense_paise"] for m in trend),
        "profit_paise": sum(m["profit_paise"] for m in trend),
        "trend": trend,
        "top_expenses": top_expenses(client, year),
        "accounts": accounts(client, as_of),
        "owed": owed(client, as_of),
        "gst_net_payable_paise": gst_net,
        "tds_payable_paise": tds_payable,
        "books": {
            "approved_through": status.approved_through,
            "signed_off_through": status.signed_off_through,
            "changed_since_approval": status.changed_since_approval,
            "close_period": client.close_period,
            "next_seal_date": _next_seal(client, today),
        },
        "attention": {
            "open_items": len(report.items),
            "blocking_unexplained": report.unexplained_blocking,
            "failing_controls": failing,
        },
    }


# ---------------------------------------------------------------------------
# The firm
# ---------------------------------------------------------------------------

SEVERITY = {"critical": 0, "high": 1, "medium": 2}


def _next_seal(client, today: datetime.date) -> datetime.date | None:
    """The first sealing date still ahead of today on the client's schedule."""
    ahead = books.seal_dates(client, upto=today + datetime.timedelta(days=400), after=today)
    return ahead[0] if ahead else None


def _seal_due(
    client, today: datetime.date, sealed_through: datetime.date | None
) -> list[datetime.date]:
    """Sealing dates that have passed unsealed, counting only those the client's books reach (a new client owes none)."""
    first = (
        JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    if first is None:
        return []
    return [d for d in books.seal_dates(client, upto=today, after=sealed_through) if d >= first]


def _tds_overdue(client, today: datetime.date) -> tuple[int, datetime.date | None]:
    unpaid, oldest = 0, None
    for month in tds.position(client):
        if month.unpaid_paise > 0 and today > month.due:
            unpaid += month.unpaid_paise
            oldest = month.due if oldest is None else min(oldest, month.due)
    return unpaid, oldest


def portfolio(membership, today: datetime.date | None = None) -> dict:
    """One row per client the person may see, what needs attention (most serious first), and what is due in the next 45 days."""
    from core.access import visible_clients

    today = today or datetime.date.today()
    overview = firm_overview(membership)
    detailed = len(overview["clients"]) <= DETAIL_LIMIT
    people = {c.pk: c for c in visible_clients(membership)}
    rows, attention, deadlines = [], [], defaultdict(list)

    for base in overview["clients"]:
        client = people.get(base["id"])
        row = {**base, "detail": detailed}
        if detailed and client is not None:
            status = books.status(client)
            report = close.close_report(client)
            overdue_tds, oldest = _tds_overdue(client, today)
            owing = owed(client, today)
            seal_due = _seal_due(client, today, status.signed_off_through)
            next_seal = _next_seal(client, today)
            failing_bank = [c for c in report.checks if c.name.startswith("bank_") and not c.ok]
            row.update(
                {
                    "approved_through": status.approved_through,
                    "changed_since_approval": status.changed_since_approval,
                    "seal_due": seal_due[-1] if seal_due else None,
                    "next_seal_date": next_seal,
                    "open_items": len(report.items),
                    "blocking_unexplained": report.unexplained_blocking,
                    "failing_controls": len([c for c in report.checks if not c.ok]),
                    "tds_overdue_paise": overdue_tds,
                    "receivables_paise": owing[partyreports.RECEIVABLES]["total_paise"],
                    "payables_paise": owing[partyreports.PAYABLES]["total_paise"],
                }
            )
            name = client.name
            if overdue_tds:
                attention.append(
                    _item(
                        "critical",
                        client,
                        f"TDS of {{amount}} was due by {oldest:%d-%m-%Y} and is not deposited.",
                        overdue_tds,
                        "tds",
                    )
                )
            if (
                seal_due
                and status.approved_through
                and status.approved_through >= seal_due[-1]
                and not status.changed_since_approval
            ):
                attention.append(
                    _item(
                        "high",
                        client,
                        f"Approved and ready to seal through {seal_due[-1]:%d-%m-%Y}.",
                        None,
                        "seal",
                    )
                )
            elif seal_due:
                attention.append(
                    _item(
                        "high",
                        client,
                        f"The books were due to be sealed through {seal_due[-1]:%d-%m-%Y}.",
                        None,
                        "seal",
                    )
                )
            if failing_bank:
                attention.append(
                    _item(
                        "high",
                        client,
                        f"{len(failing_bank)} bank account(s) do not agree with their statement.",
                        None,
                        "bank",
                    )
                )
            if report.unexplained_blocking:
                attention.append(
                    _item(
                        "high",
                        client,
                        f"{report.unexplained_blocking} open item(s) block sealing until fixed or explained.",
                        None,
                        "open_items",
                    )
                )
            if status.changed_since_approval:
                attention.append(
                    _item(
                        "medium",
                        client,
                        f"{status.changed_since_approval} entr(ies) changed since the senior approved.",
                        None,
                        "approval",
                    )
                )
            if base["months_missing"]:
                attention.append(
                    _item(
                        "medium",
                        client,
                        f"Statements are missing for {len(base['months_missing'])} month(s).",
                        None,
                        "statements",
                    )
                )
            if base["unresolved"] or base["pending_approval"]:
                attention.append(
                    _item(
                        "medium",
                        client,
                        f"{base['unresolved'] + base['pending_approval']} bank row(s) are waiting in Review.",
                        None,
                        "review",
                    )
                )
            # What falls due soon.
            for month in tds.position(client):
                if month.unpaid_paise > 0 and today <= month.due <= today + datetime.timedelta(
                    days=45
                ):
                    deadlines[(month.due, "TDS deposit")].append(name)
            if next_seal and next_seal <= today + datetime.timedelta(days=45):
                deadlines[(next_seal, "Seal the books")].append(name)
        rows.append(row)

    attention.sort(key=lambda a: (SEVERITY[a["severity"]], a["client_name"]))
    return {
        "totals": overview["totals"],
        "by_stage": overview["by_stage"],
        "clients": rows,
        "attention": attention,
        "deadlines": [
            {"date": day, "label": label, "clients": sorted(names)}
            for (day, label), names in sorted(deadlines.items())
        ],
        "detailed": detailed,
    }


def _item(severity: str, client, text: str, paise: int | None, kind: str) -> dict:
    from core.money import format_inr

    return {
        "severity": severity,
        "kind": kind,
        "client": client.pk,
        "client_name": client.name,
        "text": text.replace("{amount}", format_inr(paise) if paise is not None else ""),
        "amount_paise": paise,
    }
