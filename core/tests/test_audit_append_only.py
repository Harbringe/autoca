"""The audit log can be added to and read, never rewritten or erased, and sensitive reads are in it."""

from __future__ import annotations

import pytest
from django.db import DatabaseError, transaction

from core.db.session import firm_context
from core.models import AuditLog
from core.provisioning import create_firm

#: The retention tests below exercise core.migrations.0016's trigger directly. The "owner" connection is the one the
#: retention command actually runs on; in CI's single-role test database it is the same connection as "default", so
#: these tests prove the trigger's own date floor rather than anything about which Postgres role holds which grant
#: (that is core.migrations.0013's job, and core/tests/test_rls_isolation.py's).
pytestmark = pytest.mark.django_db(databases=["default", "owner"])


@pytest.fixture
def row():
    firm = create_firm("Audit Firm")
    with firm_context(firm.pk):
        yield AuditLog.objects.create(firm=firm, method="POST", path="/x", status_code=200)


def test_the_database_refuses_to_change_an_audit_row(row):
    with firm_context(row.firm_id), pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=row.pk).update(path="/rewritten")


def test_the_database_refuses_to_erase_an_audit_row(row):
    with firm_context(row.firm_id), pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=row.pk).delete()


def test_a_fresh_row_cannot_be_erased_through_the_owner_connection_either():
    """The retention floor is enforced by the trigger itself, not by trusting the caller to ask nicely."""
    firm = create_firm("Audit Retention Firm")
    with firm_context(firm.pk):
        fresh = AuditLog.objects.create(firm=firm, method="POST", path="/x", status_code=200)

    with pytest.raises(DatabaseError), transaction.atomic(using="owner"):
        AuditLog.objects.using("owner").filter(pk=fresh.pk).delete()


def test_a_row_past_the_retention_floor_can_be_erased_through_the_owner_connection():
    import datetime

    from django.utils import timezone

    firm = create_firm("Audit Retention Firm 2")
    old = timezone.now() - datetime.timedelta(days=31)
    with firm_context(firm.pk):
        stale = AuditLog.objects.create(firm=firm, method="POST", path="/x", status_code=200, created_at=old)

    deleted, _ = AuditLog.objects.using("owner").filter(pk=stale.pk).delete()
    assert deleted == 1


def test_an_old_row_still_cannot_be_rewritten():
    import datetime

    from django.utils import timezone

    firm = create_firm("Audit Retention Firm 3")
    old = timezone.now() - datetime.timedelta(days=31)
    with firm_context(firm.pk):
        stale = AuditLog.objects.create(firm=firm, method="POST", path="/x", status_code=200, created_at=old)

    with pytest.raises(DatabaseError), transaction.atomic(using="owner"):
        AuditLog.objects.using("owner").filter(pk=stale.pk).update(path="/rewritten")


def test_an_audit_row_can_still_be_written_and_read(row):
    with firm_context(row.firm_id):
        assert AuditLog.objects.filter(pk=row.pk).exists()
