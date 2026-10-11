"""`trim_audit_log`: deletes request-audit rows the retention window has passed, and nothing newer."""

from __future__ import annotations

import datetime

import pytest
from django.core.management import call_command
from django.db import DatabaseError
from django.utils import timezone

from core.db.session import firm_context
from core.models import AuditLog
from core.provisioning import create_firm

#: The command itself deletes through the privileged "owner" connection; these tests check what it left behind on it.
pytestmark = pytest.mark.django_db(databases=["default", "owner"])


def _row(firm, *, days_old: int):
    with firm_context(firm.pk):
        return AuditLog.objects.create(
            firm=firm, method="GET", path="/x", status_code=200,
            created_at=timezone.now() - datetime.timedelta(days=days_old),
        )


def test_a_dry_run_reports_what_would_go_and_deletes_nothing(capsys):
    firm = create_firm("Trim Firm 1")
    old = _row(firm, days_old=40)

    call_command("trim_audit_log", "--dry-run")

    assert "1" in capsys.readouterr().out
    assert AuditLog.objects.using("owner").filter(pk=old.pk).exists()


def test_rows_past_the_window_are_deleted_and_recent_ones_are_kept(capsys):
    firm = create_firm("Trim Firm 2")
    old = _row(firm, days_old=40)
    recent = _row(firm, days_old=5)

    call_command("trim_audit_log")

    assert not AuditLog.objects.using("owner").filter(pk=old.pk).exists()
    assert AuditLog.objects.using("owner").filter(pk=recent.pk).exists()


def test_a_window_shorter_than_the_database_floor_is_refused_in_words():
    firm = create_firm("Trim Firm 3")
    _row(firm, days_old=40)

    with pytest.raises(DatabaseError):
        call_command("trim_audit_log", "--days", "10")


def test_with_no_old_rows_nothing_happens(capsys):
    firm = create_firm("Trim Firm 4")
    _row(firm, days_old=5)

    call_command("trim_audit_log")

    assert "0" in capsys.readouterr().out
