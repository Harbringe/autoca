"""The database's own plan, with real timings, for the queries that dominate the client's screens, on one client. Read-only.

    python manage.py shell -c "exec(open(r'scripts/profile_explain.py', encoding='utf-8').read())"

EXPLAIN ANALYZE runs each query once and reports how long Postgres itself took (the time on the database server, with none of the
network between it and here), which join or scan is the expensive step, and how many rows each step handled. Output is plan text only:
table and index names, row counts and timings. Where a plan quotes a value (an id in a filter) it is a uuid, never a name or an amount.
"""

import re

from django.contrib.auth import get_user_model
from django.db import connection

from core.db.session import firm_context, user_context
from core.middleware.tenancy import resolve_membership
from core.models import Client

CLIENT_NAME = "Test HDFC"
MAX_LINES = 60


def _find():
    for person in get_user_model().objects.all():
        with user_context(person.pk):
            membership = resolve_membership(person)
            firm_id = membership.firm_id if membership else None
        if firm_id is None:
            continue
        with firm_context(firm_id):
            client = Client.objects.filter(name=CLIENT_NAME).first()
            if client is not None:
                return firm_id, client
    raise SystemExit(f"No client named {CLIENT_NAME!r}")


def show(title, queryset):
    print(f"\n=== {title}")
    plan = queryset.explain(analyze=True, buffers=True)
    for line in plan.splitlines()[:MAX_LINES]:
        line = re.sub(r"'[0-9a-f-]{36}'::uuid", "<id>", line)
        print("  " + line[:175])


def main():
    firm_id, client = _find()
    with firm_context(firm_id), connection.cursor() as cursor:
        for setting in ("shared_buffers", "work_mem", "effective_cache_size", "random_page_cost"):
            cursor.execute(f"SHOW {setting}")  # noqa: S608 -- a fixed list in this file
            print(f"{setting} = {cursor.fetchone()[0]}")
        cursor.execute(
            "SELECT relname, n_live_tup, seq_scan, idx_scan FROM pg_stat_user_tables "
            "WHERE relname IN ('classify_transaction_classification','banking_statement_transaction','ledger_journal_entry','ledger_journal_line') ORDER BY relname"
        )
        print("tables (name, live rows, sequential scans so far, index scans so far):")
        for row in cursor.fetchall():
            print("  ", row)

        from django.db.models import Count, Q

        from classify.engine import review_queue, unposted_in, unresolved_for
        from classify.models import ModelState
        from ledger.models import JournalEntry, JournalLine

        waiting = [ModelState.WAITING, ModelState.CLAIMED]
        ids = Client.objects.values("pk")
        show(
            "the firm overview's aggregate (all clients)",
            unposted_in(firm_id, ids)
            .values("transaction__bank_account__client_id")
            .annotate(
                unresolved=Count("pk", filter=Q(ledger__isnull=True)),
                pending=Count("pk", filter=Q(ledger__isnull=False)),
                waiting=Count("pk", filter=Q(ledger__isnull=True, model_state__in=waiting)),
            ),
        )
        show("the review screen's queue of unresolved rows (500 of them)", unresolved_for(client)[:500])
        show("the review summary's counts (the queue, banded)", review_queue(client).values("review_band"))
        show(
            "the journal entries list (500 live entries)",
            JournalEntry.objects.filter(firm_id=firm_id, client=client).order_by("-entry_date")[:500],
        )
        show(
            "the lines of those entries",
            JournalLine.objects.filter(firm_id=firm_id, entry__client=client)[:3000],
        )


main()
