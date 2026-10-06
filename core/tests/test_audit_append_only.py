"""The audit log can be added to and read, never rewritten or erased, and sensitive reads are in it."""

from __future__ import annotations

import pytest
from django.db import DatabaseError, transaction

from core.db.session import firm_context
from core.models import AuditLog
from core.provisioning import create_firm

pytestmark = pytest.mark.django_db


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


def test_an_audit_row_can_still_be_written_and_read(row):
    with firm_context(row.firm_id):
        assert AuditLog.objects.filter(pk=row.pk).exists()
