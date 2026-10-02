"""Measured figures about how the work is going, computed only from what is already stored.

Nothing here is a score and nothing ranks people. Each figure says what it counts
(the API documents the same words), and where the stored data cannot tell two
situations apart the figure says which way it errs.

Posted rows
    Entries with ``approved_at`` in the period that stand for a statement row
    (``source_transaction`` set) and are not corrections. A transfer between two of
    the client's own accounts is two statement rows but one entry, and counts once.

Automated
    A posted row nobody posted: ``approved_by`` is empty. That is set when the
    assistant posts and never rewritten, unlike the entry's marker, which a person
    clears by checking it. An automated entry that a person later edited is not
    automated any more.

Stayed / changed (accuracy)
    Stayed: a rule or model placement posted in the period that nobody has changed.
    That is an automatic post with nothing in the change log, or an entry a person
    posted without changing the placement: the row still carries the rule that placed
    it (a person's own placement clears it), or the model's suggestion with no
    placement by a person recorded against it.
    Changed, dated when it happened: a change-log item that moved an automatic (or
    model-placed) entry to other ledgers, a removal of one, a correction entry against
    one, and a person placing a row the model had already suggested.
    Not seen: a rule placement a person overrode before posting, and later changes to
    an entry a person posted from a rule placement. The log does not say where those
    placements began.
"""

from __future__ import annotations

import datetime
import statistics
from collections import defaultdict

from django.db.models import Count, Exists, Max, OuterRef, Q, Sum
from django.utils import timezone

from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import LedgerGroup, ModelState, TransactionClassification
from core.money import format_inr
from core.models import FirmMembership
from ledger.models import (
    BooksAction,
    BooksEvent,
    ChangeAction,
    EntryChange,
    EntryMarker,
    JournalEntry,
    JournalLine,
)
from ledger.overview import firm_overview
from ledger.reconciliation import NoStatementError, check_balance
from teams.models import ActivityEvent, ActivityKind

#: Books left unsigned this long after their latest entry need a look.
UNSIGNED_DAYS = 45

_MACHINE_MARKERS = (EntryMarker.AI_POSTED.value, EntryMarker.AI_REVISED.value)


def bounds(start: datetime.date, end: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    """``[start, end]`` as a half-open range of aware datetimes in the current timezone."""
    tz = timezone.get_current_timezone()
    return (
        datetime.datetime.combine(start, datetime.time.min, tzinfo=tz),
        datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz),
    )


def _blank() -> dict:
    return {"posted": 0, "automated": 0, "stayed": 0, "changed": 0}


def _lines_of(snapshot: dict) -> frozenset:
    return frozenset(
        (
            line.get("ledger_id"),
            line.get("party_id"),
            line.get("direction"),
            line.get("amount_paise"),
            line.get("rcm"),
            line.get("tds_section"),
        )
        for line in (snapshot or {}).get("lines", [])
    )


def placements(firm_id, client_ids, lo, hi) -> dict:
    """``{client_id: {"posted", "automated", "stayed", "changed"}}`` for the period."""
    out: dict = defaultdict(_blank)

    entries = (
        JournalEntry.objects.filter(
            firm_id=firm_id,
            client_id__in=client_ids,
            approved_at__gte=lo,
            approved_at__lt=hi,
            supersedes__isnull=True,
            source_transaction__isnull=False,
        )
        .annotate(
            person_edited=Exists(
                EntryChange.objects.filter(
                    entry_id=OuterRef("pk"), action=ChangeAction.EDITED, actor__isnull=False
                )
            ),
            changed=Exists(
                EntryChange.objects.filter(
                    entry_id=OuterRef("pk"), action__in=[ChangeAction.EDITED, ChangeAction.AI_REVISED]
                )
            ),
            corrected=Exists(JournalEntry.objects.filter(supersedes=OuterRef("pk"))),
            placed_by_person=Exists(
                ActivityEvent.objects.filter(
                    kind=ActivityKind.ROW_PLACED,
                    subject_id=OuterRef("source_transaction__classification__pk"),
                )
            ),
        )
        .values_list(
            "client_id",
            "approved_by_id",
            "person_edited",
            "changed",
            "corrected",
            "placed_by_person",
            "source_transaction__classification__rule_id",
            "source_transaction__classification__model_state",
        )
    )
    for client_id, approver, person_edited, changed, corrected, by_person, rule_id, model_state in entries:
        row = out[client_id]
        row["posted"] += 1
        if approver is None and not person_edited:
            row["automated"] += 1
        if changed or corrected or by_person:
            continue
        if approver is None:
            row["stayed"] += 1
        elif rule_id is not None or model_state == ModelState.DONE:
            row["stayed"] += 1

    # Changes made in the period to entries the machine placed.
    changes = EntryChange.objects.filter(
        firm_id=firm_id,
        client_id__in=client_ids,
        created_at__gte=lo,
        created_at__lt=hi,
        action__in=[ChangeAction.EDITED, ChangeAction.AI_REVISED, ChangeAction.REMOVED],
    ).values_list("client_id", "entry_id", "action", "before", "after")
    changes = list(changes)
    surviving = {
        e["pk"]: e
        for e in JournalEntry.objects.filter(pk__in=[c[1] for c in changes]).values(
            "pk", "approved_by_id", "source_transaction__classification__model_state"
        )
    }
    for client_id, entry_id, action, before, after in changes:
        if action != ChangeAction.REMOVED and _lines_of(before) == _lines_of(after):
            continue  # only the wording changed: the placement stood
        entry = surviving.get(entry_id)
        machine = (
            action == ChangeAction.AI_REVISED
            or (before or {}).get("marker") in _MACHINE_MARKERS
            or (
                entry is not None
                and (
                    entry["approved_by_id"] is None
                    or entry["source_transaction__classification__model_state"] == ModelState.DONE
                )
            )
        )
        if machine:
            out[client_id]["changed"] += 1

    # A correction entry against a machine placement.
    for client_id, approver, marker, model_state in JournalEntry.objects.filter(
        firm_id=firm_id,
        client_id__in=client_ids,
        approved_at__gte=lo,
        approved_at__lt=hi,
        supersedes__isnull=False,
    ).values_list(
        "client_id",
        "supersedes__approved_by_id",
        "supersedes__marker",
        "supersedes__source_transaction__classification__model_state",
    ):
        if approver is None or marker in _MACHINE_MARKERS or model_state == ModelState.DONE:
            out[client_id]["changed"] += 1

    # A person placing a row the model had already suggested a ledger for.
    overrides = (
        ActivityEvent.objects.filter(
            firm_id=firm_id,
            kind=ActivityKind.ROW_PLACED,
            client_id__in=client_ids,
            created_at__gte=lo,
            created_at__lt=hi,
        )
        .filter(
            Exists(
                TransactionClassification.objects.filter(
                    pk=OuterRef("subject_id"), model_state=ModelState.DONE
                )
            )
        )
        .values("client_id")
        .annotate(n=Count("pk"))
    )
    for row in overrides:
        out[row["client_id"]]["changed"] += row["n"]
    return out


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def figures(counts: dict, minutes_per_row: int) -> dict:
    return {
        "rows_posted": counts["posted"],
        "rows_automated": counts["automated"],
        "automation_share": _ratio(counts["automated"], counts["posted"]),
        "placements_stayed": counts["stayed"],
        "placements_changed": counts["changed"],
        "accuracy": _ratio(counts["stayed"], counts["stayed"] + counts["changed"]),
        "estimated_minutes_saved": counts["automated"] * minutes_per_row,
    }


# ---------------------------------------------------------------------------
# Needs attention: where the books stand now, whatever the period asked for
# ---------------------------------------------------------------------------


def _month_name(code: str) -> str:
    year, month = code.split("-")
    return datetime.date(int(year), int(month), 1).strftime("%b %Y")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def needs_attention(firm_id, overview_rows: list[dict], today: datetime.date) -> dict:
    """``{client_id: [{"code", "message"}]}`` for every client with a reason, in a fixed order."""
    ids = [row["id"] for row in overview_rows]
    reasons: dict = defaultdict(list)

    accounts = list(
        BankAccount.objects.filter(firm_id=firm_id, client_id__in=ids, is_active=True).annotate(
            last_statement_end=Max("statements__period_end")
        )
    )
    differing: dict = defaultdict(int)
    unconfirmed: dict = defaultdict(int)
    for account in accounts:
        if not account.has_opening_balance:
            unconfirmed[account.client_id] += 1
        if account.last_statement_end is None:
            continue
        try:
            check = check_balance(account, account.last_statement_end)
        except NoStatementError:
            continue
        if not check.matches:
            differing[account.client_id] += 1

    suspense = {
        r["entry__client_id"]: r["total"]
        for r in JournalLine.objects.filter(
            firm_id=firm_id, entry__client_id__in=ids, ledger_account__group=LedgerGroup.SUSPENSE
        )
        .values("entry__client_id")
        .annotate(total=Sum("signed_paise"))
        if r["total"]
    }
    latest_entry = dict(
        JournalEntry.objects.filter(firm_id=firm_id, client_id__in=ids)
        .order_by()
        .values("client_id")
        .annotate(latest=Max("entry_date"))
        .values_list("client_id", "latest")
    )

    for row in overview_rows:
        pk = row["id"]
        found = reasons[pk]
        if differing[pk]:
            found.append(
                {
                    "code": "reconciliation_difference",
                    "message": (
                        f"The books and the bank statement disagree on "
                        f"{_plural(differing[pk], 'bank account', 'bank accounts')} "
                        "at the latest statement date."
                    ),
                }
            )
        if row["months_missing"]:
            months = [_month_name(m) for m in row["months_missing"]]
            shown = ", ".join(months[:3]) + (f" and {len(months) - 3} more" if len(months) > 3 else "")
            found.append(
                {"code": "statement_month_missing", "message": f"No bank statement covers {shown}."}
            )
        if row["ai_unchecked"]:
            found.append(
                {
                    "code": "assistant_entries_unchecked",
                    "message": (
                        f"{_plural(row['ai_unchecked'], 'entry', 'entries')} posted or changed by the "
                        "assistant "
                        f"{'has' if row['ai_unchecked'] == 1 else 'have'} not been checked."
                    ),
                }
            )
        latest = latest_entry.get(pk)
        signed = row["signed_off_through"]
        if latest is not None and (signed is None or latest > signed) and (today - latest).days > UNSIGNED_DAYS:
            found.append(
                {
                    "code": "unsigned_too_long",
                    "message": (
                        f"The books are not signed off and the latest entry is dated "
                        f"{latest:%d-%m-%Y}, {(today - latest).days} days ago."
                    ),
                }
            )
        if pk in suspense:
            found.append(
                {
                    "code": "suspense_balance",
                    "message": f"Suspense holds {format_inr(abs(suspense[pk]))}; nobody has decided where it belongs.",
                }
            )
        if unconfirmed[pk]:
            found.append(
                {
                    "code": "opening_balance_unconfirmed",
                    "message": (
                        f"The opening balance is not confirmed on "
                        f"{_plural(unconfirmed[pk], 'bank account', 'bank accounts')}."
                    ),
                }
            )
    return reasons


# ---------------------------------------------------------------------------
# Turnaround: elapsed days, per person
# ---------------------------------------------------------------------------


def _days(delta: datetime.timedelta) -> float:
    return max(round(delta.total_seconds() / 86400, 2), 0.0)


def turnaround(firm_id, client_ids, lo, hi) -> dict:
    """``{user_id: {"uploads": [days], "reviews": [days]}}``."""
    out: dict = defaultdict(lambda: {"uploads": [], "reviews": []})

    statements = {
        s["pk"]: s
        for s in Statement.objects.filter(
            firm_id=firm_id,
            bank_account__client_id__in=client_ids,
            document__created_at__gte=lo,
            document__created_at__lt=hi,
            document__uploaded_by__isnull=False,
        ).values("pk", "document__created_at", "document__uploaded_by_id")
    }
    if statements:
        posted = Exists(JournalEntry.objects.filter(source_transaction=OuterRef("pk"), supersedes__isnull=True))
        rows = (
            StatementTransaction.objects.filter(statement_id__in=list(statements))
            .annotate(is_posted=posted)
            .values("statement_id")
            .annotate(
                total=Count("pk"),
                waiting=Count(
                    "pk", filter=Q(is_posted=False, classification__mirrored_entry_id__isnull=True)
                ),
            )
        )
        complete = [r["statement_id"] for r in rows if r["total"] and not r["waiting"]]
        last_posted = {
            r["source_transaction__statement_id"]: r["last"]
            for r in JournalEntry.objects.filter(
                firm_id=firm_id, source_transaction__statement_id__in=complete, supersedes__isnull=True
            )
            .values("source_transaction__statement_id")
            .annotate(last=Max("approved_at"))
        }
        for statement_id in complete:
            done = last_posted.get(statement_id)
            if done is None:
                continue
            s = statements[statement_id]
            out[s["document__uploaded_by_id"]]["uploads"].append(_days(done - s["document__created_at"]))

    signed = list(
        BooksEvent.objects.filter(
            firm_id=firm_id,
            client_id__in=client_ids,
            action=BooksAction.SIGNED_OFF,
            created_at__gte=lo,
            created_at__lt=hi,
            actor__isnull=False,
        ).values_list("client_id", "created_at", "actor_id")
    )
    if signed:
        requests: dict = defaultdict(list)
        for client_id, at in (
            BooksEvent.objects.filter(
                firm_id=firm_id,
                client_id__in={s[0] for s in signed},
                action=BooksAction.REQUESTED,
                created_at__lt=hi,
            )
            .order_by("created_at")
            .values_list("client_id", "created_at")
        ):
            requests[client_id].append(at)
        for client_id, at, actor_id in signed:
            earlier = [r for r in requests[client_id] if r <= at]
            if earlier:
                out[actor_id]["reviews"].append(_days(at - earlier[-1]))
    return out


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _people(firm_id, user_ids) -> list[dict]:
    from teams import service

    members = FirmMembership.objects.filter(firm_id=firm_id, user_id__in=list(user_ids)).select_related("user")
    return sorted(
        ({"id": str(m.pk), "name": service.label(m), "user_id": m.user_id} for m in members),
        key=lambda p: (p["name"].lower(), p["id"]),
    )


# ---------------------------------------------------------------------------
# The whole report
# ---------------------------------------------------------------------------


def firm_metrics(
    membership: FirmMembership,
    start: datetime.date,
    end: datetime.date,
    *,
    minutes_per_row: int,
    today: datetime.date | None = None,
) -> dict:
    """Every figure for the clients ``membership`` may see, for ``start`` to ``end`` inclusive."""
    today = today or timezone.localdate()
    lo, hi = bounds(start, end)
    overview = firm_overview(membership)
    rows = overview["clients"]
    ids = [row["id"] for row in rows]
    firm_id = membership.firm_id

    counts = placements(firm_id, ids, lo, hi)
    attention = needs_attention(firm_id, rows, today)
    total = _blank()
    clients = []
    for row in rows:
        mine = counts.get(row["id"], _blank())
        for key in total:
            total[key] += mine[key]
        clients.append(
            {
                "id": row["id"],
                "name": row["name"],
                **figures(mine, minutes_per_row),
                "needs_attention": attention[row["id"]],
            }
        )

    worked = turnaround(firm_id, ids, lo, hi)
    people = []
    for person in _people(firm_id, worked):
        mine = worked[person["user_id"]]
        people.append(
            {
                "member": {"id": person["id"], "name": person["name"]},
                "statements_completed": len(mine["uploads"]),
                "median_days_upload_to_posted": _median(mine["uploads"]),
                "books_signed_off": len(mine["reviews"]),
                "median_days_request_to_sign_off": _median(mine["reviews"]),
            }
        )

    return {
        "period": {"from": start, "to": end},
        "assumed_minutes_per_row": minutes_per_row,
        "is_estimate": True,
        "firm": {
            **figures(total, minutes_per_row),
            "clients": len(rows),
            "clients_needing_attention": sum(1 for c in clients if c["needs_attention"]),
        },
        "clients": clients,
        "turnaround": people,
    }
