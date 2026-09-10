"""Middleware wiring: tenant context, audit trail, and the checks that guard both."""

from __future__ import annotations

import pytest
from django.core.checks import Error
from django.test import RequestFactory

from core.checks import check_middleware_order
from core.db.session import firm_context, get_current_firm_id
from core.middleware.audit import AuditMiddleware
from core.models import AuditLog
from core.provisioning import add_member, create_firm, create_user

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


# ---------------------------------------------------------------------------
# Ordering checks
# ---------------------------------------------------------------------------


def test_shipped_middleware_order_passes_its_own_checks():
    assert check_middleware_order(None) == []


@pytest.mark.parametrize(
    ("swap", "expected_id"),
    [
        (
            (
                "core.middleware.tenancy.TenantContextMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware",
            ),
            "core.E002",
        ),
        (
            (
                "core.middleware.audit.AuditMiddleware",
                "core.middleware.tenancy.TenantContextMiddleware",
            ),
            "core.E005",
        ),
    ],
)
def test_misordered_middleware_is_rejected(settings, swap, expected_id):
    """Reordering these is a silent security regression, so make it loud."""
    mw = list(settings.MIDDLEWARE)
    first, second = swap
    i, j = mw.index(first), mw.index(second)
    mw[i], mw[j] = mw[j], mw[i]
    settings.MIDDLEWARE = mw

    results = check_middleware_order(None)
    assert any(isinstance(r, Error) and r.id == expected_id for r in results), results


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_audit_row_is_written_for_a_mutating_request():
    firm = create_firm("Firm A")
    user = create_user("audit@example.com", PASSWORD)
    membership = add_member(firm, user)

    request = RequestFactory().post("/api/things/", HTTP_USER_AGENT="pytest")
    request.user = user
    request.firm = firm
    request.membership = membership

    with firm_context(firm.pk):
        AuditMiddleware(lambda r: _response(201))(request)
        entry = AuditLog.objects.get()

    assert entry.method == "POST"
    assert entry.status_code == 201
    assert entry.user_id == user.pk
    assert entry.firm_id == firm.pk
    assert entry.request_id


def test_reads_are_not_audited():
    firm = create_firm("Firm A")
    request = RequestFactory().get("/api/things/")
    request.user = None
    request.firm = firm

    with firm_context(firm.pk):
        AuditMiddleware(lambda r: _response(200))(request)
        assert AuditLog.objects.count() == 0


def test_audit_rows_cannot_be_modified_or_deleted():
    from django.core.exceptions import ValidationError

    firm = create_firm("Firm A")
    with firm_context(firm.pk):
        entry = AuditLog.objects.create(
            firm=firm, method="POST", path="/x/", status_code=200
        )
        entry.status_code = 500
        with pytest.raises(ValidationError):
            entry.save()
        with pytest.raises(ValidationError):
            entry.delete()


def test_audit_row_lands_in_the_right_firm():
    """An audit trail that can be written into another firm's history is worse
    than none, because it is trusted."""
    firm_a = create_firm("Firm A")
    firm_b = create_firm("Firm B")

    with firm_context(firm_a.pk):
        AuditLog.objects.create(firm=firm_a, method="POST", path="/a/", status_code=200)

    with firm_context(firm_b.pk):
        assert AuditLog.objects.count() == 0


# ---------------------------------------------------------------------------
# Tenant context lifecycle
# ---------------------------------------------------------------------------


def test_context_is_established_and_torn_down():
    firm = create_firm("Firm A")
    assert not get_current_firm_id()
    with firm_context(firm.pk):
        assert get_current_firm_id() == str(firm.pk)
    assert not get_current_firm_id()


def test_user_without_a_membership_is_refused():
    from django.core.exceptions import PermissionDenied

    from core.middleware.tenancy import TenantContextMiddleware

    user = create_user("orphan@example.com", PASSWORD)
    request = RequestFactory().get("/api/me/")
    request.user = user

    with pytest.raises(PermissionDenied):
        TenantContextMiddleware(lambda r: _response(200))(request)


def _response(status):
    from django.http import HttpResponse

    return HttpResponse(status=status)
