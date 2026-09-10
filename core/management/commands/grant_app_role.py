"""Grant the application role the DML it needs, and nothing more.

Run after every `migrate`. The app role owns nothing, so Django's own tables
(sessions, migrations, content types, TOTP devices) are inaccessible to it until
granted. Firm-scoped tables are granted here too -- a GRANT is not an RLS
bypass, and the policies continue to apply.

Deliberately absent: CREATE, TRUNCATE, REFERENCES, and any privilege on the
`app` schema beyond EXECUTE on the guard functions.

    python manage.py migrate --database=owner
    python manage.py grant_app_role --database=owner
"""

from django.core.management.base import BaseCommand
from django.db import connections

from core.db.rls import APP_ROLE

# ruff: noqa: S608 -- DDL built from a module constant, not from user input.
SQL = f"""
GRANT USAGE ON SCHEMA public TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};

-- Cover tables created by future migrations without needing to re-run this.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE};

REVOKE CREATE ON SCHEMA public FROM {APP_ROLE};
"""


class Command(BaseCommand):
    help = "Grant the autoca_app role the DML privileges it needs."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="owner")

    def handle(self, *args, **options):
        alias = options["database"]
        with connections[alias].cursor() as cursor:
            cursor.execute(SQL)
        self.stdout.write(self.style.SUCCESS(f"Granted {APP_ROLE} DML on public via {alias!r}."))
