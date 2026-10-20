"""What the row-level security check costs per row, measured on the real database without changing anything.

    python manage.py shell -c "exec(open(r'scripts/profile_rls.py', encoding='utf-8').read())"

Read-only. It times the check on a made-up series of rows (no table is touched) in four forms, and the real review-summary count with the
database's own EXPLAIN ANALYZE. The one temporary function it defines lives only in this session's temporary schema and is gone when the
connection closes.
"""

import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection

from core.db.session import firm_context, user_context
from core.middleware.tenancy import resolve_membership
from core.models import Client

ROWS = 200_000
GUC = settings.TENANT_GUC


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


def bench(cursor, label, where):
    sql = f"SELECT count(*) FROM generate_series(1, {ROWS}) AS g WHERE {where}"  # noqa: S608 -- fixed text from this file, no input
    cursor.execute(sql)
    cursor.fetchone()  # warm
    best = min(_once(cursor, sql) for _ in range(3))
    print(f"  {label:<58} {best:8.1f} ms for {ROWS:,} rows  = {best * 1000 / ROWS:6.2f} us per row")


def _once(cursor, sql):
    started = time.perf_counter()
    cursor.execute(sql)
    cursor.fetchone()
    return (time.perf_counter() - started) * 1000


def main():
    firm_id = _firm()
    with firm_context(firm_id), connection.cursor() as cursor:
        print("the check, per row:")
        bench(cursor, "no check at all (the floor)", "true")
        bench(cursor, "app.current_firm_id()            [today: plpgsql]", "app.current_firm_id() IS NOT NULL")
        bench(cursor, "(SELECT app.current_firm_id())   [evaluated once]", "(SELECT app.current_firm_id()) IS NOT NULL")
        bench(cursor, "inline expression                [no function]", f"nullif(current_setting('{GUC}', true), '')::uuid IS NOT NULL")
        try:
            cursor.execute("CREATE FUNCTION pg_temp.no_firm() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT NULL::uuid WHERE false $$")
            cursor.execute(
                f"CREATE FUNCTION pg_temp.firm_id() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT coalesce(nullif(current_setting('{GUC}', true), '')::uuid, pg_temp.no_firm()) $$"
            )
            bench(cursor, "SQL function, inlinable          [candidate]", "pg_temp.firm_id() IS NOT NULL")
        except Exception as exc:  # noqa: BLE001
            print(f"  (the candidate could not be created here: {type(exc).__name__}: {str(exc)[:80]})")

        print("\nthe real review summary count, with EXPLAIN ANALYZE:")
        from classify.engine import unresolved_for

        client = Client.objects.order_by("name").first()
        plan = unresolved_for(client).explain(analyze=True, buffers=True)
        for line in plan.splitlines()[:40]:
            print("  " + line[:170])


main()
