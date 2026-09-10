"""Row factories for the cross-tenant isolation suite.

Every firm-scoped model needs an entry in ``FACTORIES``. This is not
boilerplate for its own sake -- ``test_rls_isolation.py`` fails the build if a
firm-scoped model has no factory, which is what makes the isolation suite grow
along with the schema instead of quietly falling behind it.

Adding a model to the system therefore forces you to say how to create one, and
the suite immediately starts attacking it from the wrong tenant.
"""

from __future__ import annotations

import datetime
import uuid

from core.models import AuditLog, Client, Firm, FirmMembership, Role, User


def _client(firm, **kw):
    return Client.objects.create(
        firm=firm,
        name=kw.get("name", f"Client {uuid.uuid4().hex[:8]}"),
        fy_start=kw.get("fy_start", datetime.date(2026, 4, 1)),
    )


def _membership(firm, **kw):
    user = kw.get("user") or User.objects.create_user(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password="correct-horse-battery"
    )
    return FirmMembership.objects.create(firm=firm, user=user, role=kw.get("role", Role.STAFF))


def _audit(firm, **kw):
    return AuditLog.objects.create(
        firm=firm,
        user=kw.get("user"),
        method="POST",
        path="/test/",
        status_code=200,
        request_id=uuid.uuid4().hex,
    )


#: model -> callable(firm, **kwargs) -> instance
FACTORIES = {
    Client: _client,
    FirmMembership: _membership,
    AuditLog: _audit,
}

#: Firm is firm-scoped by primary key rather than by a firm_id column, so it is
#: handled separately by the suite rather than through FACTORIES.
TENANT_ROOT = Firm
