"""Delete request-audit rows past their retention window.

``core_audit_log`` holds one row per mutating request plus the reads ``core.middleware.audit.SENSITIVE_READS``
names, and the application role may only ever SELECT and INSERT into it (``core/migrations/0013``): nothing this
command does runs as that role, or it would fail before reaching a row. It runs on the privileged ``owner``
connection instead, the same one migrations use, which the database's own retention floor
(``core/migrations/0016_audit_log_retention.py``) still refuses to let touch anything newer than the floor,
whatever window this command is asked to use.

Run nightly, e.g. from a systemd timer (``deploy/install-log-retention.sh`` installs one, matching the pattern
``deploy/install-backups.sh`` already uses for the database backup):

    python manage.py trim_audit_log --database=owner
"""

from __future__ import annotations

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AuditLog


class Command(BaseCommand):
    help = "Delete core_audit_log rows older than --days (default settings.AUDIT_LOG_RETENTION_DAYS)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.AUDIT_LOG_RETENTION_DAYS)
        parser.add_argument("--dry-run", action="store_true", help="Say how many rows would go. Delete nothing.")

    def handle(self, *args, days, dry_run, **options):
        cutoff = timezone.now() - datetime.timedelta(days=days)
        queryset = AuditLog.objects.using("owner").filter(created_at__lt=cutoff)

        if dry_run:
            self.stdout.write(f"Would delete {queryset.count()} audit-log rows older than {cutoff:%Y-%m-%d}.")
            return

        deleted, _ = queryset.delete()
        self.stdout.write(f"Deleted {deleted} audit-log rows older than {cutoff:%Y-%m-%d}.")
