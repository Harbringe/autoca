"""Where the time goes in the requests a client's screens make: a read-only profile of the real views on one client.

Run it inside the Django shell with the live settings (the way docs/LIVE.md describes), or against any database:

    python manage.py shell -c "exec(open(r'scripts/profile_requests.py', encoding='utf-8').read())"

It calls the views directly (no HTTP, no sign-in, nothing written) for the client named in CLIENT_NAME, once warm and once measured, with
the sharing of results (core.freshness) off so the real work is what is timed. For each request it prints the time, how many queries ran
and how long they took together, how big the answer is, the project functions that took longest, and the slowest queries with every value
removed. Names, amounts and ids never appear in the output.
"""

import cProfile
import io
import pstats
import re
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIRequestFactory, force_authenticate

from core.db.session import firm_context, user_context
from core.middleware.tenancy import resolve_membership
from core.models import Client, FirmMembership

CLIENT_NAME = "Test HDFC"
FY = 2025
PROJECT = ("\\api\\", "/api/", "\\ledger\\", "/ledger/", "\\classify\\", "/classify/", "\\core\\", "/core/", "\\banking\\", "/banking/")

settings.FRESHNESS_TTL = 0  # time the work itself, not a shared copy of it
factory = APIRequestFactory()


def _clean(sql: str) -> str:
    sql = re.sub(r"'(?:[^']|'')*'", "?", sql)  # string values
    sql = re.sub(r"\b\d+(?:\.\d+)?\b", "?", sql)  # numbers
    sql = re.sub(r"\(\?(?:, ?\?)+\)", "(?, ...)", sql)  # value lists
    sql = re.sub(r'"[a-z_]+"\."([a-z_]+)"', r"\1", sql)  # table.column -> column
    return re.sub(r"\s+", " ", sql)[:170]


def _find():
    for person in get_user_model().objects.all():
        with user_context(person.pk):
            membership = resolve_membership(person)
            firm_id = membership.firm_id if membership else None
        if firm_id is None:
            continue
        with firm_context(firm_id):
            client = Client.objects.filter(name=CLIENT_NAME).first()
            if client is None:
                continue
            best = (
                FirmMembership.objects.filter(firm_id=firm_id, is_active=True)
                .select_related("user")
                .order_by("-is_owner", "role")
                .first()
            )
            return firm_id, client, best
    raise SystemExit(f"No client named {CLIENT_NAME!r} found.")


def _request(path, membership, firm_id):
    request = factory.get(path)
    force_authenticate(request, user=membership.user)
    request.membership, request.firm, request.firm_id = membership, membership.firm, firm_id
    return request


def _views(client):
    from api.views.banking import StatementViewSet
    from api.views.classify import ReviewQueueViewSet
    from api.views.ledger import JournalEntryViewSet, ReportView
    from api.views.overview import FirmOverviewView

    c = str(client.pk)
    v1 = "/api/v1"
    return [
        ("trial balance", ReportView.as_view({"get": "trial_balance"}), f"{v1}/clients/{c}/reports/trial-balance/?fy={FY}", {"client_id": c}),
        ("profit and loss", ReportView.as_view({"get": "profit_and_loss"}), f"{v1}/clients/{c}/reports/profit-and-loss/?fy={FY}", {"client_id": c}),
        ("balance sheet", ReportView.as_view({"get": "balance_sheet"}), f"{v1}/clients/{c}/reports/balance-sheet/?fy={FY}", {"client_id": c}),
        ("review queue (500 rows)", ReviewQueueViewSet.as_view({"get": "list"}), f"{v1}/clients/{c}/review-queue/?stage=unresolved&page_size=500", {"client_id": c}),
        ("review queue (50 rows)", ReviewQueueViewSet.as_view({"get": "list"}), f"{v1}/clients/{c}/review-queue/?stage=unresolved&page_size=50", {"client_id": c}),
        ("review summary", ReviewQueueViewSet.as_view({"get": "summary"}), f"{v1}/clients/{c}/review-queue/summary/", {"client_id": c}),
        ("statements list", StatementViewSet.as_view({"get": "list"}), f"{v1}/clients/{c}/statements/?page_size=100", {"client_id": c}),
        ("journal entries", JournalEntryViewSet.as_view({"get": "list"}), f"{v1}/journal-entries/?client={c}&live=true&page_size=500", {}),
        ("firm overview", FirmOverviewView.as_view(), f"{v1}/firm/overview/", {}),
    ]


def _alerts_calls(client, membership):
    from ledger import alerts as alerts_mod

    return [
        ("firm alerts (all clients)", lambda: alerts_mod.firm_alerts(membership)),
        ("one client's alerts", lambda: alerts_mod.client_alerts_for(membership, client)),
    ]


def measure(name, call):
    call()  # warm: connections, caches inside Postgres, imports
    profile = cProfile.Profile()
    with CaptureQueriesContext(connection) as queries:
        started = time.perf_counter()
        profile.enable()
        result = call()
        profile.disable()
        wall = (time.perf_counter() - started) * 1000
    db_ms = sum(float(q["time"]) for q in queries.captured_queries) * 1000
    size = ""
    if hasattr(result, "render"):
        result.render()
        size = f", {len(result.content) / 1024:.0f} KB answer, HTTP {result.status_code}"
    print(f"\n=== {name}: {wall:.0f} ms total, {len(queries)} queries taking {db_ms:.0f} ms{size}")
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream)
    rows = []
    for (path, line, func), (_cc, _nc, tt, ct, _callers) in stats.stats.items():
        if any(p in path for p in PROJECT) and "site-packages" not in path and not func.startswith("<"):
            rows.append((ct * 1000, tt * 1000, f"{path.split('autoca')[-1].split('app')[-1][-48:]}:{line} {func}"))
    for ct, tt, label in sorted(rows, reverse=True)[:7]:
        print(f"   {ct:7.0f} ms in, {tt:6.0f} ms own  {label}")
    slow = sorted(queries.captured_queries, key=lambda q: -float(q["time"]))[:3]
    for q in slow:
        print(f"   query {float(q['time']) * 1000:6.0f} ms  {_clean(q['sql'])}")


def main():
    firm_id, client, membership = _find()
    print(f"profiling as a {membership.role} on the client named {CLIENT_NAME!r}; sharing of results is off")
    with firm_context(firm_id):
        for name, view, path, kwargs in _views(client):
            measure(name, lambda view=view, path=path, kwargs=kwargs: view(_request(path, membership, firm_id), **kwargs))
        for name, call in _alerts_calls(client, membership):
            measure(name, call)


main()
