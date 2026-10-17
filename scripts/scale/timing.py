"""Time the queries behind the screens that will slow down first, on the scratch database, as the app's own login under row-level security.

    python /scale/timing.py            # a table: query, milliseconds, rows, whether Postgres read a whole table
    python /scale/timing.py --plans    # also print each EXPLAIN (ANALYZE, BUFFERS)

Each query is run three times; the table shows the fastest and the slowest, since the first is usually cold. The heavy client is the first
one of the first firm that fill.py made.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings  # noqa: E402
from django.db.models import Count, Sum  # noqa: E402

from banking.models import BankAccount, StatementTransaction  # noqa: E402
from classify.models import LedgerAccount, Party, TransactionClassification  # noqa: E402
from core.db.session import firm_context  # noqa: E402
from core.models import Client  # noqa: E402
from ledger.models import JournalEntry, JournalLine  # noqa: E402

NAMESPACE = uuid.UUID("5ca1e000-0000-4000-8000-000000000001")


def guard() -> None:
    db = settings.DATABASES["default"]
    if db["NAME"] != "autoca_scale_test" or db["HOST"] != "db":
        sys.exit(
            f"Refusing: this times only the scratch database autoca_scale_test, not {db['NAME']} on {db['HOST']}."
        )


def main() -> None:
    guard()
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", action="store_true")
    args = ap.parse_args()

    firm_id = uuid.uuid5(NAMESPACE, "firm-0")
    with firm_context(firm_id):
        client = Client.objects.order_by("name").first()
        account = BankAccount.objects.filter(client=client).order_by("account_last4").first()
        ledger = LedgerAccount.objects.filter(client=client, name="Ledger 0001").first()
        print(
            f"client {client.name}: {StatementTransaction.objects.filter(bank_account__client=client).count():,} bank rows, "
            f"{JournalEntry.objects.filter(client=client).count():,} entries, {JournalLine.objects.filter(entry__client=client).count():,} lines\n"
        )

        queue = TransactionClassification.objects.filter(
            transaction__bank_account__client=client, needs_review=True
        )
        cases = [
            ("Review queue: how many", lambda: queue, "count"),
            (
                "Review queue: first page of 50",
                lambda: queue.select_related("transaction").order_by("transaction__value_date")[
                    :50
                ],
                "list",
            ),
            (
                "Review queue: the WHOLE queue (what the browser downloads)",
                lambda: queue.select_related("transaction"),
                "list",
            ),
            (
                "Bank rows of one account: a page",
                lambda: StatementTransaction.objects.filter(bank_account=account).order_by(
                    "value_date", "row_number"
                )[:50],
                "list",
            ),
            (
                "Bank rows of one account: one month",
                lambda: StatementTransaction.objects.filter(
                    bank_account=account, value_date__year=2024, value_date__month=6
                ),
                "count",
            ),
            (
                "Entries: a page of 50",
                lambda: JournalEntry.objects.filter(client=client).order_by(
                    "entry_date", "entry_no"
                )[:50],
                "list",
            ),
            (
                "Entries: one day (day book)",
                lambda: JournalEntry.objects.filter(client=client, entry_date="2024-06-12"),
                "count",
            ),
            (
                "One ledger's balance",
                lambda: JournalLine.objects.filter(
                    entry__client=client, ledger_account=ledger
                ).aggregate(t=Sum("signed_paise")),
                "agg",
            ),
            (
                "Trial balance: every ledger's total",
                lambda: JournalLine.objects.filter(entry__client=client)
                .values("ledger_account")
                .annotate(t=Sum("signed_paise"), n=Count("id")),
                "list",
            ),
            (
                "Parties: a page of 50",
                lambda: Party.objects.filter(client=client).order_by("canonical_name")[:50],
                "list",
            ),
            (
                "Parties: search by name",
                lambda: Party.objects.filter(client=client, canonical_name__icontains="0420"),
                "list",
            ),
        ]

        print(f"{'query':62} {'fastest':>9} {'slowest':>9} {'rows':>9}  whole-table read?")
        for label, make, mode in cases:
            times, size = [], 0
            for _ in range(3):
                qs = make()
                t0 = time.perf_counter()
                if mode == "count":
                    size = qs.count()
                elif mode == "agg":
                    size = 1 if qs else 0
                else:
                    size = len(list(qs))
                times.append((time.perf_counter() - t0) * 1000)
            plan = make().explain(analyze=True, buffers=True) if mode in ("list", "count") else ""
            scan = "SEQ SCAN" if "Seq Scan" in plan else ""
            print(f"{label:62} {min(times):8.0f}ms {max(times):8.0f}ms {size:9,}  {scan}")
            if args.plans and plan:
                print(plan + "\n")


if __name__ == "__main__":
    main()
