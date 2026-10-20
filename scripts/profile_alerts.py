"""Where the alerts' cost goes: for every client of the firm, each open-item detector and each part of the close report, timed one at a time.

    python manage.py shell -c "exec(open(r'scripts/profile_alerts.py', encoding='utf-8').read())"

Read-only. For each part it adds up, over all the clients, the queries it ran and the time it took, and says which client was the slowest.
Output is the names of the detectors and checks and numbers: no client names, amounts or ids. Over a tunnel every query carries the
network's delay, so compare the parts by how many queries they ran as much as by milliseconds.
"""

import time
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.db.session import firm_context, user_context
from core.middleware.tenancy import resolve_membership
from core.models import Client

settings.FRESHNESS_TTL = 0


def _firm():
    for person in get_user_model().objects.all():
        with user_context(person.pk):
            membership = resolve_membership(person)
            firm_id = membership.firm_id if membership else None
        if firm_id is not None:
            with firm_context(firm_id):
                if Client.objects.exists():
                    return firm_id
    raise SystemExit("no firm found")


def timed(call):
    with CaptureQueriesContext(connection) as queries:
        started = time.perf_counter()
        call()
        ms = (time.perf_counter() - started) * 1000
    return ms, len(queries)


def main():
    from ledger import books, close, openitems

    firm_id = _firm()
    totals = defaultdict(lambda: [0.0, 0, 0.0])  # name -> [ms, queries, slowest client ms]
    with firm_context(firm_id):
        clients = list(Client.objects.order_by("name"))
        print(f"{len(clients)} clients in the firm\n")
        for client in clients:
            parts = [("books.status", lambda c=client: books.status(c))]
            for kind, (_title, function) in openitems._DETECTORS.items():
                parts.append((f"open item: {kind}", lambda c=client, f=function: list(f(c))))
            parts.append(("close_report (everything)", lambda c=client: close.close_report(c)))
            parts.append(("close_report._checks only", lambda c=client: close._checks(c, None)))
            for name, call in parts:
                call()  # warm
                ms, queries = timed(call)
                row = totals[name]
                row[0] += ms
                row[1] += queries
                row[2] = max(row[2], ms)
    width = max(len(name) for name in totals)
    print(f"{'part':<{width}}  {'ms':>8}  {'queries':>8}  {'slowest one client':>20}")
    for name, (ms, queries, worst) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
        print(f"{name:<{width}}  {ms:8.0f}  {queries:8d}  {worst:17.0f} ms")


main()
