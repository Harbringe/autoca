"""Where every visible client's books stand, worked out for all of them at once.

The client list and the dashboard need one line per client. Asking each client's
own endpoints costs three requests a client; this reads the same facts with a
fixed number of aggregate queries however many clients there are. The stage rule
is the one the client list has always shown as "next step" (it used to live in
``ClientsScreen.tsx``): the first of these that holds, in this order.

    no statement on file              upload
    a row with no ledger              place
    a row with a ledger, unposted     post
    a review request is open          sign_off
    entries after the last sign-off   send_for_review
    otherwise                         none (signed off to date)
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from django.db.models import Count, F, OuterRef, Q, Subquery

from banking.models import Statement
from classify.engine import unposted_in
from classify.models import ModelState
from core.access import visible_clients
from ledger.models import BooksAction, BooksEvent, EntryMarker, JournalEntry

STAGES = ("no_statements", "needs_ledger", "ready_to_post", "in_review", "ready_for_review", "signed_off")


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _next_step(stage: str, *, unresolved: int, pending: int, signed: datetime.date | None = None) -> dict:
    if stage == "no_statements":
        return {"code": "upload", "label": "Upload a bank statement", "count": 0}
    if stage == "needs_ledger":
        verb = "needs" if unresolved == 1 else "need"
        return {"code": "place", "label": f"{_plural(unresolved, 'row')} {verb} a ledger", "count": unresolved}
    if stage == "ready_to_post":
        return {"code": "post", "label": f"{_plural(pending, 'row')} ready to post", "count": pending}
    if stage == "in_review":
        return {"code": "sign_off", "label": "Sent for review", "count": 0}
    if stage == "ready_for_review":
        after = f" (after {signed:%d-%m-%Y})" if signed else ""
        return {"code": "send_for_review", "label": f"Send for review{after}", "count": 0}
    return {"code": "none", "label": "Signed off to date", "count": 0}


def _months(start: datetime.date, end: datetime.date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _missing_months(spans: dict) -> list[str]:
    """Months inside an account's own run of statements that no statement of it touches.

    Per bank account, so a second account opened later is not flagged for the
    months before it existed, and an account with a gap is flagged whatever the
    client's other accounts show.
    """
    missing: set[tuple[int, int]] = set()
    for periods in spans.values():
        covered: set[tuple[int, int]] = set()
        for start, end in periods:
            covered.update(_months(start, end))
        first = min(start for start, _ in periods)
        last = max(end for _, end in periods)
        missing.update(m for m in _months(first, last) if m not in covered)
    return [f"{y:04d}-{m:02d}" for y, m in sorted(missing)]


def firm_overview(membership) -> dict:
    """One row per client ``membership`` may see, plus firm totals. Four queries."""
    visible = visible_clients(membership)
    ids = visible.values("pk")

    last_action = BooksEvent.objects.filter(client=OuterRef("pk")).order_by("-created_at", "-id").values("action")[:1]
    clients = list(
        visible.select_related("lead__user")
        .annotate(last_books_action=Subquery(last_action))
        .order_by("name", "pk")
    )

    waiting_states = [ModelState.WAITING, ModelState.CLAIMED]
    queue = {
        row["transaction__bank_account__client_id"]: row
        for row in unposted_in(membership.firm_id, ids)
        .values("transaction__bank_account__client_id")
        .annotate(
            unresolved=Count("pk", filter=Q(ledger__isnull=True)),
            pending=Count("pk", filter=Q(ledger__isnull=False)),
            waiting=Count("pk", filter=Q(ledger__isnull=True, model_state__in=waiting_states)),
        )
    }

    # Entries after the client's own sign-off date, as the books screen counts them.
    unchecked = {
        row["client_id"]: row
        for row in JournalEntry.objects.filter(firm_id=membership.firm_id, client__in=ids)
        .filter(Q(client__signed_off_through__isnull=True) | Q(entry_date__gt=F("client__signed_off_through")))
        .values("client_id")
        .annotate(
            posted=Count("pk", filter=Q(marker=EntryMarker.AI_POSTED)),
            revised=Count("pk", filter=Q(marker=EntryMarker.AI_REVISED)),
        )
    }

    spans: dict = defaultdict(lambda: defaultdict(list))
    latest: dict = {}
    for client_id, account_id, start, end in Statement.objects.filter(
        firm_id=membership.firm_id, bank_account__client__in=ids
    ).values_list("bank_account__client_id", "bank_account_id", "period_start", "period_end"):
        spans[client_id][account_id].append((start, end))
        if client_id not in latest or end > latest[client_id]:
            latest[client_id] = end

    rows = []
    by_stage = dict.fromkeys(STAGES, 0)
    totals = {
        "clients": len(clients),
        "unresolved": 0,
        "pending_approval": 0,
        "assistant_waiting": 0,
        "ai_unchecked": 0,
        "review_pending": 0,
        "months_missing": 0,
    }
    for client in clients:
        q = queue.get(client.pk, {})
        unresolved, pending, waiting = q.get("unresolved", 0), q.get("pending", 0), q.get("waiting", 0)
        u = unchecked.get(client.pk, {})
        ai_unchecked = u.get("posted", 0) + u.get("revised", 0)
        review_pending = client.last_books_action == BooksAction.REQUESTED
        last_end = latest.get(client.pk)
        signed = client.signed_off_through
        unsigned = last_end is not None and not (signed is not None and signed >= last_end)

        if last_end is None:
            stage = "no_statements"
        elif unresolved:
            stage = "needs_ledger"
        elif pending:
            stage = "ready_to_post"
        elif review_pending:
            stage = "in_review"
        elif unsigned:
            stage = "ready_for_review"
        else:
            stage = "signed_off"
        by_stage[stage] += 1

        missing = _missing_months(spans[client.pk]) if client.pk in spans else []
        lead = client.lead
        rows.append(
            {
                "id": client.pk,
                "name": client.name,
                "lead": {"id": str(lead.pk), "name": lead.user.full_name or lead.user.email} if lead else None,
                "stage": stage,
                "next_step": _next_step(stage, unresolved=unresolved, pending=pending, signed=signed),
                "unresolved": unresolved,
                "pending_approval": pending,
                "assistant_waiting": waiting,
                "ai_unchecked": ai_unchecked,
                "review_pending": review_pending,
                "signed_off_through": signed,
                "last_statement_end": last_end,
                "months_missing": missing,
            }
        )
        totals["unresolved"] += unresolved
        totals["pending_approval"] += pending
        totals["assistant_waiting"] += waiting
        totals["ai_unchecked"] += ai_unchecked
        totals["review_pending"] += int(review_pending)
        totals["months_missing"] += len(missing)
    return {"totals": totals, "by_stage": by_stage, "clients": rows}
