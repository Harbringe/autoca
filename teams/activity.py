"""Recording work, and reporting it.

What each number means, and where it comes from:

    Statements uploaded   documents_document.uploaded_by       (always recorded)
    Entries approved      ledger_journal_entry.approved_by, not a correction
    Entries corrected     ledger_journal_entry.approved_by, a correction
    Entries posted        ledger_journal_entry.approved_by, either kind (see METRIC_NOTES)
    Books sent for review ledger_books_event, action REQUESTED, by the actor
    Rows placed           teams_activity_event row.placed      (from this release)
    Ledgers created       teams_activity_event ledger.created
    Rules written         teams_activity_event rule.created
    Proposals decided     teams_activity_event proposal.decided
    Model runs            teams_activity_event model.run

Open work is not history: it is what is still unplaced or unapproved on the
clients a person can see, right now.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Count, Max, Sum
from django.db.models.functions import TruncDate

from classify.engine import pending_approval, unresolved_for
from core.models import Client
from documents.models import Document
from ledger.models import BooksAction, BooksEvent, JournalEntry
from teams.models import ActivityEvent, ActivityKind

#: The order and wording the UI shows.
METRICS: list[tuple[str, str]] = [
    ("statements_uploaded", "Statements uploaded"),
    ("rows_placed", "Rows placed"),
    ("entries_approved", "Entries approved"),
    ("entries_corrected", "Entries corrected"),
    ("entries_posted", "Entries posted"),
    ("books_sent_for_review", "Books sent for review"),
    ("ledgers_created", "Ledgers created"),
    ("rules_written", "Rules written by hand"),
    ("proposals_decided", "Ledger proposals decided"),
    ("model_runs", "Model runs"),
]

#: What a number means where its label alone would mislead. Sent beside the label.
METRIC_NOTES: dict[str, str] = {
    "entries_posted": (
        "Every entry that carries this person's name: first-time approvals and corrections together, "
        "so it is Entries approved plus Entries corrected. Entries the assistant posted by itself "
        "carry nobody's name and are not counted for anyone."
    ),
}


def metric_list() -> list[dict]:
    return [{"key": key, "label": label, "note": METRIC_NOTES.get(key, "")} for key, label in METRICS]


_EVENT_METRIC = {
    ActivityKind.ROW_PLACED: "rows_placed",
    ActivityKind.LEDGER_CREATED: "ledgers_created",
    ActivityKind.RULE_CREATED: "rules_written",
    ActivityKind.PROPOSAL_DECIDED: "proposals_decided",
    ActivityKind.MODEL_RUN: "model_runs",
}


def record(*, firm_id, user, kind: str, client=None, quantity: int = 1, subject_id=None) -> None:
    """Count one piece of work. Call inside the transaction doing the work."""
    if user is None or not getattr(user, "is_authenticated", False) or quantity <= 0:
        return
    ActivityEvent.objects.create(
        firm_id=firm_id,
        user_id=user.pk,
        client_id=getattr(client, "pk", client),
        kind=kind,
        quantity=quantity,
        subject_id=subject_id,
    )


@dataclass
class Period:
    start: datetime.datetime
    end: datetime.datetime


def _blank() -> dict[str, int]:
    return {key: 0 for key, _ in METRICS}


@dataclass
class WorkReport:
    totals: dict[str, int] = field(default_factory=_blank)
    by_client: dict = field(default_factory=lambda: defaultdict(_blank))
    by_day: dict = field(default_factory=lambda: defaultdict(int))


def work_by_user(firm_id, user_ids, period: Period) -> dict:
    """{user_id: WorkReport} for every user id asked about."""
    reports = {uid: WorkReport() for uid in user_ids}

    def add(user_id, client_id, metric, amount, day=None):
        report = reports.get(user_id)
        if report is None or not amount:
            return
        report.totals[metric] += amount
        report.by_client[client_id][metric] += amount
        if day is not None:
            report.by_day[day.isoformat()] += amount

    uploads = (
        Document.objects.filter(
            firm_id=firm_id,
            uploaded_by_id__in=user_ids,
            created_at__gte=period.start,
            created_at__lt=period.end,
        )
        .annotate(day=TruncDate("created_at"))
        .values("uploaded_by_id", "client_id", "day")
        .annotate(n=Count("id"))
    )
    for row in uploads:
        add(row["uploaded_by_id"], row["client_id"], "statements_uploaded", row["n"], row["day"])

    entries = (
        JournalEntry.objects.filter(
            firm_id=firm_id,
            approved_by_id__in=user_ids,
            approved_at__gte=period.start,
            approved_at__lt=period.end,
        )
        .annotate(day=TruncDate("approved_at"))
        .values("approved_by_id", "client_id", "day", "supersedes_id")
        .annotate(n=Count("id"))
    )
    for row in entries:
        metric = "entries_corrected" if row["supersedes_id"] else "entries_approved"
        add(row["approved_by_id"], row["client_id"], metric, row["n"], row["day"])
        # The same entries counted once more, as posted. No day: the day chart already has them.
        add(row["approved_by_id"], row["client_id"], "entries_posted", row["n"])

    sent = (
        BooksEvent.objects.filter(
            firm_id=firm_id,
            actor_id__in=user_ids,
            action=BooksAction.REQUESTED,
            created_at__gte=period.start,
            created_at__lt=period.end,
        )
        .annotate(day=TruncDate("created_at"))
        .values("actor_id", "client_id", "day")
        .annotate(n=Count("id"))
    )
    for row in sent:
        add(row["actor_id"], row["client_id"], "books_sent_for_review", row["n"], row["day"])

    events = (
        ActivityEvent.objects.filter(
            firm_id=firm_id,
            user_id__in=user_ids,
            created_at__gte=period.start,
            created_at__lt=period.end,
        )
        .annotate(day=TruncDate("created_at"))
        .values("user_id", "client_id", "kind", "day")
        .annotate(n=Sum("quantity"))
    )
    for row in events:
        metric = _EVENT_METRIC.get(row["kind"])
        if metric:
            add(row["user_id"], row["client_id"], metric, row["n"], row["day"])

    return reports


def open_work(clients) -> dict:
    """{client_id: {"unresolved": n, "pending_approval": n, "books_to_send": bool}} for these clients."""
    clients = list(clients)
    counts = {
        client.pk: {
            "unresolved": unresolved_for(client).count(),
            "pending_approval": pending_approval(client).count(),
        }
        for client in clients
    }
    to_send = _books_to_send(clients, counts)
    return {pk: {**c, "books_to_send": to_send[pk]} for pk, c in counts.items()}


def _books_to_send(clients, counts) -> dict:
    """Could a request for review be made now, and would it say something new?

    True when every row is placed and posted (the same condition ``ledger.books.request_review``
    enforces), no request is already waiting for a senior, and there are entries dated after the
    last sign-off (or any, if nothing is signed off).
    """
    ids = [c.pk for c in clients]
    latest_action = dict(
        BooksEvent.objects.filter(client_id__in=ids)
        .order_by("client_id", "-created_at", "-id")
        .distinct("client_id")
        .values_list("client_id", "action")
    )
    newest_entry = dict(
        JournalEntry.objects.filter(client_id__in=ids)
        .order_by()
        .values("client_id")
        .annotate(latest=Max("entry_date"))
        .values_list("client_id", "latest")
    )
    out = {}
    for client in clients:
        pk = client.pk
        latest = newest_entry.get(pk)
        out[pk] = bool(
            latest is not None
            and not counts[pk]["unresolved"]
            and not counts[pk]["pending_approval"]
            and latest_action.get(pk) != BooksAction.REQUESTED
            and (client.signed_off_through is None or latest > client.signed_off_through)
        )
    return out


def client_names(firm_id, ids) -> dict:
    ids = [i for i in ids if i]
    return dict(Client.objects.filter(firm_id=firm_id, pk__in=ids).values_list("pk", "name"))
