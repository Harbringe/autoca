"""Alerts: everything that wants a person's attention, each with where to click to deal with it.

Alerts are **computed, never stored**, from the same sources the rest of the product reads: the firm overview (rows waiting,
missing statement months), the close page (failing controls, open items), the books' approval and seal state, and the TDS
position. A fixed problem is simply no longer an alert, so there is nothing to dismiss and nothing to go stale.

Every alert names the module it belongs to (so each module can show its own) and carries a ``to`` path plus a ``search``
dictionary that open the exact screen where it is fixed. The firm portfolio's attention list is built from these too, so a
problem is described once.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from core.money import format_inr
from ledger import books, close, tds
from ledger.models import JournalEntry

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}

#: Modules an alert can belong to. They match the sidebar's modules.
MODULES = ("bank", "bookkeeping", "reports", "gst", "documents")

#: Open items that are fixed on their own screen rather than the general "To fix" list.
ITEM_SCREEN = {
    "tds_not_deposited": "tds",
    "tds_payment_without_challan": "tds",
    "fixed_asset_unregistered": "assets",
    "invoice_unbooked": "invoices",
}

#: Due-soon TDS is called high when it is this close, medium before that.
DUE_SOON_DAYS = 7
DUE_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Alert:
    kind: str
    severity: str
    module: str
    client_id: object
    client_name: str
    #: A few words: what is wrong.
    title: str
    #: A sentence: what, how much, since when.
    detail: str
    #: Where to go to fix it, as a path, and the query it needs.
    to: str
    search: dict = field(default_factory=dict)
    amount_paise: int | None = None
    #: How many things this alert stands for (rows, entries, items).
    count: int = 1
    #: The date this was due or falls due, where there is one (a sealing date, a TDS deposit date).
    due: datetime.date | None = None


def is_overdue(alert: Alert) -> bool:
    """A sealing date has passed unsealed, or TDS is past its deposit date (the one critical alert)."""
    return alert.severity == "critical" or alert.kind == "seal"


def _path(client, screen: str = "") -> str:
    return f"/clients/{client.pk}/{screen}".rstrip("/")


def _tds_alerts(client, today: datetime.date):
    overdue, oldest, due_soon = 0, None, None
    for month in tds.position(client):
        if month.unpaid_paise <= 0:
            continue
        if today > month.due:
            overdue += month.unpaid_paise
            oldest = month.due if oldest is None else min(oldest, month.due)
        elif month.due <= today + datetime.timedelta(days=DUE_WINDOW_DAYS):
            amount, day = month.unpaid_paise, month.due
            due_soon = (
                (amount, day) if due_soon is None else (due_soon[0] + amount, min(due_soon[1], day))
            )
    return overdue, oldest, due_soon


def client_alerts(
    client,
    *,
    base: dict,
    today: datetime.date,
    include_money: bool = True,
    detailed: bool = True,
    status=None,
    report=None,
) -> list[Alert]:
    """Every alert for one client. ``base`` is the client's row from the firm overview.

    ``status`` and ``report`` may be passed when the caller already has them, so the close page is not computed twice.
    Without ``detailed`` only what the overview already knows is reported, which keeps a very large firm quick.
    """
    name, out = client.name, []

    def add(
        kind, severity, module, title, detail, screen, search=None, *, amount=None, count=1, due=None
    ):
        out.append(
            Alert(
                kind,
                severity,
                module,
                client.pk,
                name,
                title,
                detail,
                _path(client, screen),
                search or {},
                amount,
                count,
                due,
            )
        )

    if base["unresolved"]:
        n = base["unresolved"]
        add(
            "review",
            "medium",
            "bank",
            "Rows need a ledger",
            f"{n} bank row(s) have no ledger yet.",
            "review",
            {"stage": "unresolved"},
            count=n,
        )
    if base["pending_approval"]:
        n = base["pending_approval"]
        add(
            "review",
            "medium",
            "bank",
            "Rows ready to post",
            f"{n} placed bank row(s) are waiting to be posted.",
            "review",
            {"stage": "pending_approval"},
            count=n,
        )
    if base["months_missing"]:
        n = len(base["months_missing"])
        add(
            "statements",
            "medium",
            "bank",
            "A statement month is missing",
            f"No statement covers {n} month(s) inside the run of statements.",
            "statements",
            count=n,
        )
    if base["ai_unchecked"]:
        n = base["ai_unchecked"]
        add(
            "unchecked",
            "medium",
            "bookkeeping",
            "Assistant entries need checking",
            f"{n} entr(ies) the assistant posted have not been checked.",
            "daybook",
            count=n,
        )
    if base["review_pending"]:
        add(
            "review_pending",
            "medium",
            "bookkeeping",
            "Books are waiting for a senior",
            "The books were sent for review and nobody has decided yet.",
            "books",
        )

    if not detailed:
        return out

    status = status or books.status(client)
    report = report or close.close_report(client)

    for check in report.checks:
        if check.ok:
            continue
        if check.name.startswith("bank_"):
            add(
                "bank",
                "high",
                "bank",
                "A bank account does not agree with its statement",
                check.detail or check.title,
                "statements",
            )
        else:
            add("control", "high", "bookkeeping", check.title, check.detail or check.title, "books")

    # Open items, one alert per kind so a long list does not drown the feed. Each goes to the screen that fixes it.
    by_kind: dict[str, list] = {}
    for item in report.items:
        by_kind.setdefault(item.item.kind, []).append(item)
    for kind, items in by_kind.items():
        blocking = any(i.blocking and not i.explained for i in items)
        n = len(items)
        add(
            kind,
            "high" if blocking else "medium",
            "bookkeeping",
            items[0].title,
            f"{n} item(s): {items[0].item.summary}"
            + (" Blocks sealing until fixed or explained." if blocking else ""),
            ITEM_SCREEN.get(kind, "open-items"),
            count=n,
        )

    first_entry = (
        JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    if first_entry is not None:
        due = [
            d
            for d in books.seal_dates(client, upto=today, after=status.signed_off_through)
            if d >= first_entry
        ]
        if due:
            latest = due[-1]
            if books.ready_to_seal(status, latest):
                add(
                    "seal",
                    "high",
                    "bookkeeping",
                    "Approved and ready to seal",
                    f"Approved and ready to seal through {latest:%d-%m-%Y}.",
                    "books",
                    due=latest,
                )
            else:
                add(
                    "seal",
                    "high",
                    "bookkeeping",
                    "Books are due to be sealed",
                    f"The books were due to be sealed through {latest:%d-%m-%Y}.",
                    "books",
                    due=latest,
                )
    if status.changed_since_approval:
        n = status.changed_since_approval
        add(
            "approval",
            "medium",
            "bookkeeping",
            "Entries changed after approval",
            f"{n} entr(ies) changed since the senior approved.",
            "books",
            count=n,
        )

    if include_money:
        overdue, oldest, due_soon = _tds_alerts(client, today)
        if overdue:
            add(
                "tds",
                "critical",
                "bookkeeping",
                "TDS is overdue",
                f"TDS of {format_inr(overdue)} was due by {oldest:%d-%m-%Y} and is not deposited.",
                "tds",
                amount=overdue,
                due=oldest,
            )
        if due_soon:
            amount, day = due_soon
            severity = "high" if (day - today).days <= DUE_SOON_DAYS else "medium"
            add(
                "tds_due",
                severity,
                "bookkeeping",
                "TDS is due soon",
                f"TDS of {format_inr(amount)} is due by {day:%d-%m-%Y}.",
                "tds",
                amount=amount,
                due=day,
            )
    return out


def sort_alerts(alerts: list[Alert]) -> list[Alert]:
    return sorted(
        alerts, key=lambda a: (SEVERITY_ORDER[a.severity], a.client_name.lower(), a.module, a.kind)
    )


def firm_alerts(
    membership, *, today: datetime.date | None = None, include_money: bool = True
) -> list[Alert]:
    """Alerts for every client the person may see, most serious first."""
    from core.access import visible_clients
    from ledger.overview import firm_overview

    today = today or datetime.date.today()
    overview = firm_overview(membership)
    detailed = len(overview["clients"]) <= 60
    people = {c.pk: c for c in visible_clients(membership)}
    out: list[Alert] = []
    for base in overview["clients"]:
        client = people.get(base["id"])
        if client is not None:
            out.extend(
                client_alerts(
                    client, base=base, today=today, include_money=include_money, detailed=detailed
                )
            )
    return sort_alerts(out)


def client_alerts_for(
    membership, client, *, today: datetime.date | None = None, include_money: bool = True
) -> list[Alert]:
    from ledger.overview import firm_overview

    today = today or datetime.date.today()
    base = next(
        (row for row in firm_overview(membership)["clients"] if row["id"] == client.pk), None
    )
    if base is None:
        return []
    return sort_alerts(client_alerts(client, base=base, today=today, include_money=include_money))


def summarise(alerts: list[Alert]) -> dict:
    """Counts the bell and the module badges show."""
    by_module = dict.fromkeys(MODULES, 0)
    by_severity = dict.fromkeys(SEVERITY_ORDER, 0)
    for alert in alerts:
        by_module[alert.module] = by_module.get(alert.module, 0) + 1
        by_severity[alert.severity] += 1
    return {"total": len(alerts), "by_module": by_module, "by_severity": by_severity}
