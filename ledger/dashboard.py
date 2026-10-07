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
from django.utils import timezone

from banking.models import BankAccount
from core.fy import fy_bounds
from ledger import alerts as alerts_mod
from ledger import books, close, partyreports, tds
from ledger.models import JournalEntry, JournalLine
from ledger.overview import client_missing_months, firm_overview
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
            "aging": {label: report.bucket_paise(label) for label in partyreports.BUCKET_LABELS},
            "top": [
                {"name": p.party.canonical_name, "amount_paise": p.total_paise}
                for p in top
                if p.total_paise
            ],
        }
    return result


#: ``(key, label, controls it needs, open-item kinds it needs)``. A control is ready-to-read when it passes; a name ending in
#: ``_`` stands for every control that starts with it (one per bank account).
_REPORTS = (
    ("pnl", "Profit and Loss", ("rows_posted", "suspense_clear"), ()),
    ("balance_sheet", "Balance Sheet", ("rows_posted", "suspense_clear", "bank_"), ()),
    ("trial_balance", "Trial Balance", ("rows_posted", "suspense_clear"), ()),
    ("receivables", "Receivables", ("rows_posted",), ("party_out_of_balance",)),
    ("payables", "Payables", ("rows_posted",), ("party_out_of_balance",)),
    ("tds", "TDS", ("rows_posted",), ()),
    ("gst", "GST", ("rows_posted",), ()),
)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def reports_ready(client, report, missing_months: list[str]) -> list[dict]:
    """Whether each report can be opened and trusted now, and in plain words why not.

    A report is ready when the client has posted entries, no month of statements is missing, and no control the report needs
    is failing on the close page (``report``, already computed by the caller). One query of its own, for "has entries".
    """
    has_entries = JournalEntry.objects.filter(firm_id=client.firm_id, client=client).exists()
    failing = {c.name: c for c in report.checks if not c.ok}
    kinds = {i.item.kind for i in report.items if not i.explained}
    out = []
    for key, label, needs, item_kinds in _REPORTS:
        reason = None
        if not has_entries:
            reason = "Nothing has been posted yet."
        elif missing_months:
            n = len(missing_months)
            reason = f"{_plural(n, 'month', 'months')} of statements {'is' if n == 1 else 'are'} missing."
        else:
            for need in needs:
                hit = next(
                    (
                        c
                        for name, c in failing.items()
                        if name == need or (need.endswith("_") and name.startswith(need))
                    ),
                    None,
                )
                if hit is None:
                    continue
                if need == "rows_posted":
                    reason = hit.detail or hit.title
                elif need == "suspense_clear":
                    reason = "Some entries are parked in Suspense and have no ledger yet."
                else:
                    reason = "A bank account does not agree with its statement."
                break
            if reason is None and kinds.intersection(item_kinds):
                reason = "A party's ledger does not agree with its bills."
        out.append({"key": key, "label": label, "ready": reason is None, "reason": reason})
    return out


def _prior_year(client, year: int) -> tuple[int | None, int | None]:
    """Income and expense of the year before ``year``, or ``(None, None)`` when nothing was posted to either."""
    trend = monthly_trend(client, year - 1)
    if not any(m["income_paise"] or m["expense_paise"] for m in trend):
        return None, None
    return sum(m["income_paise"] for m in trend), sum(m["expense_paise"] for m in trend)


def client_snapshot(client, year: int, today: datetime.date | None = None) -> dict:
    """One client's position. Per client, a fixed handful of queries; nothing is shared across clients."""
    today = today or datetime.date.today()
    start, end = fy_bounds(year)
    as_of = min(today, end)
    trend = monthly_trend(client, year)
    prior_income, prior_expense = _prior_year(client, year)
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
        "prior_income_paise": prior_income,
        "prior_expense_paise": prior_expense,
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
        "reports_ready": reports_ready(client, report, client_missing_months(client)),
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


def client_health(
    *, months_missing: int, failing_controls: int, seal_due, tds_overdue_paise: int
) -> str:
    """The one rule for how a client is doing: ``overdue`` (TDS past its deposit date), else ``at_risk`` (a statement
    month missing, a control failing, or a sealing date passed unsealed), else ``on_track``."""
    if tds_overdue_paise > 0:
        return "overdue"
    if months_missing or failing_controls or seal_due is not None:
        return "at_risk"
    return "on_track"


def _oldest_request_days(status, today: datetime.date) -> int | None:
    if not status.review_pending or status.requested_at is None:
        return None
    return max((today - timezone.localtime(status.requested_at).date()).days, 0)


def portfolio(
    membership, today: datetime.date | None = None, *, include_money: bool = True
) -> dict:
    """One row per client the person may see, what needs attention (most serious first), and what is due in the next 45 days.

    Bulk: the stage, queue and missing-month figures (``firm_overview``, a fixed number of aggregate queries). Per client
    (only up to ``DETAIL_LIMIT`` clients): books status, close report, TDS position, receivables and payables, alerts.
    The money roll-up (totals, ageing, top receivables) is summed from those per-client figures, so it adds no queries and
    is left out without ``include_money`` or beyond ``DETAIL_LIMIT``.
    """
    from core.access import visible_clients

    today = today or datetime.date.today()
    overview = firm_overview(membership)
    detailed = len(overview["clients"]) <= DETAIL_LIMIT
    people = {c.pk: c for c in visible_clients(membership)}
    rows, attention, deadlines = [], [], defaultdict(list)
    receivables_total = payables_total = 0
    aging = {
        side: dict.fromkeys(partyreports.BUCKET_LABELS, 0)
        for side in (partyreports.RECEIVABLES, partyreports.PAYABLES)
    }
    top_receivables = []

    for base in overview["clients"]:
        client = people.get(base["id"])
        row = {**base, "detail": detailed}
        if detailed and client is not None:
            status = books.status(client)
            report = close.close_report(client)
            overdue_tds = _tds_overdue(client, today)[0] if include_money else 0
            owing = owed(client, today) if include_money else None
            seal_due = _seal_due(client, today, status.signed_off_through)
            next_seal = _next_seal(client, today)
            row.update(
                {
                    "approved_through": status.approved_through,
                    "changed_since_approval": status.changed_since_approval,
                    "seal_due": seal_due[-1] if seal_due else None,
                    "next_seal_date": next_seal,
                    "open_items": len(report.items),
                    "blocking_unexplained": report.unexplained_blocking,
                    "failing_controls": len([c for c in report.checks if not c.ok]),
                    "ready_to_seal": books.ready_to_seal(status, seal_due[-1] if seal_due else None),
                    "oldest_pending_approval_days": _oldest_request_days(status, today),
                }
            )
            if owing is not None:
                row["receivables_paise"] = owing[partyreports.RECEIVABLES]["total_paise"]
                row["payables_paise"] = owing[partyreports.PAYABLES]["total_paise"]
                row["tds_overdue_paise"] = overdue_tds
                receivables_total += row["receivables_paise"]
                payables_total += row["payables_paise"]
                for side in aging:
                    for label, amount in owing[side]["aging"].items():
                        aging[side][label] += amount
                if row["receivables_paise"] > 0:
                    top_receivables.append((row["receivables_paise"], client.name, client.pk))
            name = client.name
            alerts = alerts_mod.client_alerts(
                client,
                base=base,
                today=today,
                include_money=include_money,
                status=status,
                report=report,
            )
            attention.extend(_attention(alert) for alert in alerts)
            # What falls due soon.
            for month in tds.position(client) if include_money else ():
                if month.unpaid_paise > 0 and today <= month.due <= today + datetime.timedelta(
                    days=45
                ):
                    deadlines[(month.due, "TDS deposit")].append(name)
            if next_seal and next_seal <= today + datetime.timedelta(days=45):
                deadlines[(next_seal, "Seal the books")].append(name)
        elif client is not None:
            alerts = alerts_mod.client_alerts(
                client, base=base, today=today, include_money=include_money, detailed=False
            )
            attention.extend(_attention(alert) for alert in alerts)
        row["health"] = client_health(
            months_missing=len(base["months_missing"]),
            failing_controls=row.get("failing_controls", 0),
            seal_due=row.get("seal_due"),
            tds_overdue_paise=row.get("tds_overdue_paise", 0),
        )
        rows.append(row)

    attention.sort(key=lambda a: (SEVERITY[a["severity"]], a["client_name"]))
    result = {
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
    if include_money and detailed:
        top_receivables.sort(key=lambda t: (-t[0], t[1].lower()))
        result.update(
            {
                "receivables_total_paise": receivables_total,
                "payables_total_paise": payables_total,
                "aging": {
                    side: [{"bucket": label, "amount_paise": amount} for label, amount in buckets.items()]
                    for side, buckets in aging.items()
                },
                "top_receivables": [
                    {"client": pk, "client_name": name, "amount_paise": amount}
                    for amount, name, pk in top_receivables[:5]
                ],
            }
        )
    return result


def _attention(alert) -> dict:
    return {
        "severity": alert.severity,
        "kind": alert.kind,
        "client": alert.client_id,
        "client_name": alert.client_name,
        "text": alert.detail,
        "amount_paise": alert.amount_paise,
        "to": alert.to,
        "search": alert.search,
    }
