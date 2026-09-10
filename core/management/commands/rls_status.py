"""Report the live RLS posture of the database.

Reads what Postgres actually believes, not what the migrations intended. Useful
after a restore, after a manual fix, or when a check fails and you want to see
which table is wrong.

    python manage.py rls_status
"""

from django.core.management.base import BaseCommand
from django.db import connections

QUERY = """
SELECT c.relname                AS table_name,
       c.relrowsecurity         AS rls_enabled,
       c.relforcerowsecurity    AS rls_forced,
       count(p.polname)         AS policies
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_policy p ON p.polrelid = c.oid
WHERE n.nspname = 'public' AND c.relkind = 'r'
GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity
ORDER BY c.relname;
"""


class Command(BaseCommand):
    help = "Show ENABLE/FORCE row-level security and policy counts per table."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        from core.db.introspect import firm_scoped_tables

        expected = firm_scoped_tables()

        with connections[options["database"]].cursor() as cursor:
            cursor.execute(QUERY)
            rows = cursor.fetchall()

        width = max((len(r[0]) for r in rows), default=10)
        self.stdout.write(f"{'table':<{width}}  enabled  forced  policies  scoped")
        problems = 0

        for name, enabled, forced, policies in rows:
            scoped = name in expected
            ok = (enabled and forced and policies) if scoped else True
            line = (
                f"{name:<{width}}  {str(bool(enabled)):<7}  {str(bool(forced)):<6}  "
                f"{policies:<8}  {'yes' if scoped else '-'}"
            )
            if not ok:
                problems += 1
                self.stdout.write(self.style.ERROR(line))
            else:
                self.stdout.write(line)

        missing = expected - {r[0] for r in rows}
        for name in sorted(missing):
            problems += 1
            self.stdout.write(self.style.ERROR(f"{name}: firm-scoped model has no table"))

        if problems:
            self.stdout.write(self.style.ERROR(f"\n{problems} problem(s) found."))
        else:
            self.stdout.write(self.style.SUCCESS("\nEvery firm-scoped table is protected."))
