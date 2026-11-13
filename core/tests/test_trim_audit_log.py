"""`trim_audit_log`: deletes request-audit rows the retention window has passed, and nothing newer.

Needs ``app.trim_audit_log`` installed, which needs ``autoca_platform_reader`` (``superadmin/setup_sql/role.sql``),
a one-time step as Postgres's own superuser -- not present in CI's ephemeral database, the same shape as
``superadmin/tests/test_superadmin.py``'s own skip for the platform-reader role.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connections
from django.utils import timezone

from core import retention_sql as sql
from core.db.session import firm_context
from core.models import AuditLog
from core.provisioning import create_firm

# transaction=True: the function runs on the owner connection, which cannot see rows an open test transaction has not committed.
pytestmark = pytest.mark.django_db(databases=["default", "owner"], transaction=True)


@pytest.fixture
def installed():
    with connections["owner"].cursor() as cursor:
        if not sql.reader_role_usable(cursor):
            pytest.skip("autoca_platform_reader is not set up on this Postgres cluster")
        cursor.execute(sql.CREATE_SQL)


def _row(firm, *, days_old: int):
    with firm_context(firm.pk):
        return AuditLog.objects.create(
            firm=firm, method="GET", path="/x", status_code=200,
            created_at=timezone.now() - datetime.timedelta(days=days_old),
        )


def test_a_dry_run_reports_what_would_go_and_deletes_nothing(installed, capsys):
    firm = create_firm("Trim Firm 1")
    old = _row(firm, days_old=40)

    call_command("trim_audit_log", "--dry-run")

    assert "1" in capsys.readouterr().out
    with firm_context(firm.pk):
        assert AuditLog.objects.filter(pk=old.pk).exists()


def test_rows_past_the_window_are_deleted_and_recent_ones_are_kept(installed, capsys):
    firm = create_firm("Trim Firm 2")
    old = _row(firm, days_old=40)
    recent = _row(firm, days_old=5)

    call_command("trim_audit_log")

    with firm_context(firm.pk):
        assert not AuditLog.objects.filter(pk=old.pk).exists()
        assert AuditLog.objects.filter(pk=recent.pk).exists()


def test_a_window_shorter_than_the_database_floor_is_refused_in_words(installed):
    firm = create_firm("Trim Firm 3")
    _row(firm, days_old=40)

    with pytest.raises(DatabaseError, match="retention window"):
        call_command("trim_audit_log", "--days", "10")


def test_with_no_old_rows_nothing_happens(installed, capsys):
    firm = create_firm("Trim Firm 4")
    _row(firm, days_old=5)

    call_command("trim_audit_log")

    assert "0" in capsys.readouterr().out


def test_without_install_the_command_refuses_in_words():
    with connections["owner"].cursor() as cursor:
        cursor.execute(sql.DROP_SQL)

    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="install_log_retention"):
        call_command("trim_audit_log")
