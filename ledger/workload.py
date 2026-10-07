"""How much work arrives, how much is finished, and who has what: counts of work, never a rating of people.

Three views, all read from stored timestamps (no history table, so nothing here says how a stock figure was last week):

* ``work_flow``: statement rows received per week against journal entries finished per week.
* ``people``: one row of five counts per team member, for a firm administrator or a Senior CA.
* ``me_work``: the same counts for one member's own clients, a daily series and what to do next.

Definitions, used identically everywhere:

Received
    Bank statement rows (``StatementTransaction``) in statements whose document was uploaded in the period.
Finished
    Journal entries with ``approved_at`` in the period that are not corrections (``supersedes`` empty). An entry the
    assistant posted has no ``approved_by``: it counts for the firm and the team, never for a person.
Assigned clients
    The clients a member is assigned to (``ClientAssignment``) or leads, restricted to what the caller may see.
Open items
    Rows to place + rows to post + assistant entries nobody has checked, summed over the member's clients.
Overdue
    Alerts on the member's clients that are overdue: TDS past its deposit date, or a sealing date passed unsealed.
Waiting on others
    Per client, one for each statement month missing (waiting on the client) and one when the books were sent for a
    senior's decision and nobody has decided (waiting on a senior).
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db.models import Count
from django.db.models.functions import TruncDate

from banking.models import StatementTransaction
from core.access import sees_all_clients, visible_clients
from core.models import ClientAssignment
from ledger import alerts as alerts_mod
from ledger.dashboard import DETAIL_LIMIT
from ledger.metrics import bounds
from ledger.models import JournalEntry
from ledger.overview import firm_overview
from teams import service as team_service

MAX_DAYS = 366
NEXT_TASKS = 8


def week_start(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def _days(start: datetime.date, end: datetime.date):
    for offset in range((end - start).days + 1):
        yield start + datetime.timedelta(days=offset)


def _received(firm_id, ids, lo, hi):
    return StatementTransaction.objects.filter(
        firm_id=firm_id,
        bank_account__client_id__in=ids,
        statement__document__created_at__gte=lo,
        statement__document__created_at__lt=hi,
    )


def _finished(firm_id, ids, lo, hi):
    return JournalEntry.objects.filter(
        firm_id=firm_id,
        client_id__in=ids,
        approved_at__gte=lo,
        approved_at__lt=hi,
        supersedes__isnull=True,
    )


def _per_day(queryset, field: str) -> dict[datetime.date, int]:
    rows = (
        queryset.annotate(day=TruncDate(field))
        .values("day")
        .annotate(n=Count("pk"))
        .order_by("day")
    )
    return {row["day"]: row["n"] for row in rows}


def work_flow(membership, start: datetime.date, end: datetime.date) -> dict:
    """Weekly received and finished for the clients ``membership`` may see, with the period before for comparison.

    Four aggregate queries in all, whatever the number of clients: two grouped by day for the period and two counts for the
    period before. The visible clients are a subquery inside each, never a list. Nothing is per client.
    """
    firm_id = membership.firm_id
    ids = visible_clients(membership).values("pk")
    lo, hi = bounds(start, end)
    received = _per_day(_received(firm_id, ids, lo, hi), "statement__document__created_at")
    finished = _per_day(_finished(firm_id, ids, lo, hi), "approved_at")

    weeks: dict[datetime.date, dict] = {}
    cursor = week_start(start)
    while cursor <= end:
        weeks[cursor] = {"week_start": cursor, "received": 0, "finished": 0}
        cursor += datetime.timedelta(days=7)
    for key, series in (("received", received), ("finished", finished)):
        for day, n in series.items():
            if (week := weeks.get(week_start(day))) is not None:
                week[key] += n

    length = (end - start).days + 1
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=length - 1)
    plo, phi = bounds(prev_start, prev_end)
    return {
        "scope": "firm" if sees_all_clients(membership) else "team",
        "period": {"from": start, "to": end},
        "weekly": list(weeks.values()),
        "totals": {
            "received": sum(received.values()),
            "finished": sum(finished.values()),
            "prev_received": _received(firm_id, ids, plo, phi).count(),
            "prev_finished": _finished(firm_id, ids, plo, phi).count(),
        },
    }


def _client_figures(membership, wanted: set, overview_rows: list[dict], today, include_money: bool):
    """``({client_id: {"open", "waiting", "overdue", "alerts", "name"}}, detailed)`` for the wanted clients.

    The alerts are worked out in full only while there are ``DETAIL_LIMIT`` wanted clients or fewer.

    Per client: the alerts need each client's close report, books status and TDS position (the same work the portfolio
    does per client). The open and waiting counts come from the overview rows already in hand.
    """
    detailed = len(wanted) <= DETAIL_LIMIT
    clients = {c.pk: c for c in visible_clients(membership).filter(pk__in=wanted)}
    out = {}
    for base in overview_rows:
        client = clients.get(base["id"])
        if client is None:
            continue
        found = alerts_mod.client_alerts(
            client, base=base, today=today, include_money=include_money, detailed=detailed
        )
        out[base["id"]] = {
            "name": base["name"],
            "open": base["unresolved"] + base["pending_approval"] + base["ai_unchecked"],
            "waiting": len(base["months_missing"]) + int(base["review_pending"]),
            "overdue": sum(1 for a in found if alerts_mod.is_overdue(a)),
            "alerts": found,
        }
    return out, detailed


def people(
    membership,
    start: datetime.date,
    end: datetime.date,
    today: datetime.date,
    *,
    include_money: bool,
) -> dict:
    """One row per active member the caller may see (an administrator: everyone; a Senior CA: themselves and their team).

    Bulk (a fixed number of queries): the client overview, the assignments, and finished entries grouped by approver.
    Per client (only clients with someone assigned): the alerts behind ``overdue``, detailed only while no more than
    ``DETAIL_LIMIT`` clients have someone on them. Nothing is looped per person per client.
    """
    firm_id = membership.firm_id
    members = sorted(
        team_service.visible_members(membership).filter(is_active=True),
        key=lambda m: (team_service.label(m).lower(), str(m.pk)),
    )
    overview_rows = firm_overview(membership)["clients"]
    visible = {row["id"] for row in overview_rows}
    key_of = {str(m.pk): m for m in members}

    mine: dict[str, set] = defaultdict(set)
    for client_id, member_id in ClientAssignment.objects.filter(
        firm_id=firm_id, membership_id__in=[m.pk for m in members], client_id__in=visible
    ).values_list("client_id", "membership_id"):
        mine[str(member_id)].add(client_id)
    for row in overview_rows:
        if row["lead"] and row["lead"]["id"] in key_of:
            mine[row["lead"]["id"]].add(row["id"])

    wanted = set().union(*mine.values()) if mine else set()
    figures, detailed = _client_figures(membership, wanted, overview_rows, today, include_money)

    lo, hi = bounds(start, end)
    done = {
        row["approved_by_id"]: row["n"]
        for row in _finished(firm_id, visible, lo, hi)
        .filter(approved_by_id__in=[m.user_id for m in members])
        .values("approved_by_id")
        .annotate(n=Count("pk"))
        .order_by()
    }

    rows = []
    for member in members:
        theirs = [figures[c] for c in mine.get(str(member.pk), ()) if c in figures]
        rows.append(
            {
                "member_id": member.pk,
                "name": team_service.label(member),
                "role": member.role,
                "assigned_clients": len(mine.get(str(member.pk), ())),
                "open_items": sum(f["open"] for f in theirs),
                "finished_in_period": done.get(member.user_id, 0),
                "overdue": sum(f["overdue"] for f in theirs),
                "waiting_on_others": sum(f["waiting"] for f in theirs),
            }
        )
    return {
        "period": {"from": start, "to": end},
        "detailed": detailed,
        "people": rows,
    }


def _task_order(alert):
    return (
        0 if alerts_mod.is_overdue(alert) else 1,
        alerts_mod.SEVERITY_ORDER[alert.severity],
        alert.due or datetime.date.max,
        alert.client_name.lower(),
        alert.kind,
    )


def me_work(
    membership,
    start: datetime.date,
    end: datetime.date,
    today: datetime.date,
    *,
    include_money: bool,
) -> dict:
    """The caller's own work. Own data only: nothing here reads another member's counts.

    Bulk: the client overview and the day-by-day series of what the caller finished (two queries). Per client (only the
    caller's own assigned or led clients): the alerts behind ``overdue`` and ``next_tasks``.
    """
    overview_rows = firm_overview(membership)["clients"]
    visible = {row["id"] for row in overview_rows}
    mine = set(
        ClientAssignment.objects.filter(
            firm_id=membership.firm_id, membership=membership, client_id__in=visible
        ).values_list("client_id", flat=True)
    )
    mine |= {
        row["id"]
        for row in overview_rows
        if row["lead"] and row["lead"]["id"] == str(membership.pk)
    }
    figures, _ = _client_figures(membership, mine, overview_rows, today, include_money)

    lo, hi = bounds(start, end)
    per_day = _per_day(
        _finished(membership.firm_id, visible, lo, hi).filter(approved_by_id=membership.user_id),
        "approved_at",
    )
    tasks = sorted((a for f in figures.values() for a in f["alerts"]), key=_task_order)
    return {
        "period": {"from": start, "to": end},
        "assigned_clients": len(figures),
        "open_items": sum(f["open"] for f in figures.values()),
        "overdue": sum(f["overdue"] for f in figures.values()),
        "waiting": sum(f["waiting"] for f in figures.values()),
        "finished_in_period": sum(per_day.values()),
        "daily": [{"date": day, "finished": per_day.get(day, 0)} for day in _days(start, end)],
        "next_tasks": [
            {
                "client": a.client_id,
                "client_name": a.client_name,
                "title": a.title,
                "due": a.due,
                "to": a.to,
                "search": a.search,
                "severity": a.severity,
            }
            for a in tasks[:NEXT_TASKS]
        ],
        "clients": sorted(
            ({"id": cid, "name": f["name"], "open_items": f["open"]} for cid, f in figures.items()),
            key=lambda c: (c["name"].lower(), str(c["id"])),
        ),
    }
