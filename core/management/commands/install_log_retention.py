"""One-time setup for audit-log retention.

    python manage.py install_log_retention --database=owner

Installs ``app.trim_audit_log(integer, boolean)``, the function ``trim_audit_log`` (the nightly job) calls. Needs
``autoca_platform_reader`` to already exist (``superadmin/setup_sql/role.sql``, run once as Postgres's own
superuser); without it, this says so plainly and installs nothing, the same shape as
``python manage.py superadmin install``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connections

from core import retention_sql as sql


class Command(BaseCommand):
    help = "Install app.trim_audit_log(integer, boolean), the function the audit-log retention job calls."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="owner")

    def handle(self, *args, database, **options):
        with connections[database].cursor() as cursor:
            usable = sql.reader_role_usable(cursor)
            if not usable:
                self.stdout.write(f"reader role usable: {usable}")
                self.stdout.write("Run superadmin/setup_sql/role.sql as the `postgres` role first.")
                return
            cursor.execute(sql.CREATE_SQL)
        self.stdout.write(self.style.SUCCESS("app.trim_audit_log installed."))
