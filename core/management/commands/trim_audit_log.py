"""Delete request-audit rows past their retention window.

Calls ``app.trim_audit_log(integer, boolean)`` (``core/retention_sql.py``), the one function allowed to remove a
``core_audit_log`` row across every firm at once. ``core.management.commands.install_log_retention`` must have been
run once first; without it, this refuses in words rather than with a bare Postgres error.

Run nightly, e.g. from a systemd timer (``deploy/install-log-retention.sh`` installs one, matching the pattern
``deploy/install-backups.sh`` already uses for the database backup):

    python manage.py trim_audit_log --database=owner
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from core import retention_sql as sql


class Command(BaseCommand):
    help = "Delete core_audit_log rows older than --days (default settings.AUDIT_LOG_RETENTION_DAYS)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.AUDIT_LOG_RETENTION_DAYS)
        parser.add_argument("--dry-run", action="store_true", help="Say how many rows would go. Delete nothing.")

    def handle(self, *args, days, dry_run, **options):
        with connections["owner"].cursor() as cursor:
            if not sql.installed(cursor):
                raise CommandError(
                    "app.trim_audit_log is not installed. Run `python manage.py install_log_retention` first."
                )
            cursor.execute("SELECT app.trim_audit_log(%s, %s)", [days, dry_run])
            count = cursor.fetchone()[0]

        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(f"{verb} {count} audit-log rows older than {days} days.")
