"""Fixtures for the API suite.

Signing in for a test is more involved than ``force_login`` because a session
needs a verified second factor before it may reach anything firm-scoped. That is
the product working correctly, so the helper does the real thing -- creates a
confirmed TOTP device and marks the session as having used it -- rather than
disabling the middleware.
"""

from __future__ import annotations

import datetime

import pytest
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement
from classify.seeds import seed_client
from core.db.session import firm_context
from core.models import FirmMembership, Role, User
from core.provisioning import create_client, create_firm

PASSWORD = "correct-horse-battery-staple"


def sign_in(user) -> APIClient:
    """An API client whose session has a password *and* a second factor.

    django_otp records the verified device on the session; setting it is what
    ``otp_login`` does, and doing it directly avoids needing a live TOTP code.
    """
    device, _ = TOTPDevice.objects.get_or_create(user=user, name="test", confirmed=True)
    http = APIClient()
    http.force_login(user)
    session = http.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    http.cookies[session.__class__.__name__ and "sessionid"] = session.session_key
    return http


def member(firm, role=Role.STAFF, email=None) -> FirmMembership:
    user = User.objects.create_user(
        email=email or f"{role.lower()}@example.test", password=PASSWORD
    )
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


@pytest.fixture
def firm():
    return create_firm("API Test Firm")


@pytest.fixture
def client_record(firm):
    return create_client(firm, "Acme Traders", datetime.date(2025, 4, 1))


@pytest.fixture
def staff(firm):
    return member(firm, Role.STAFF, "staff@example.test")


@pytest.fixture
def senior(firm):
    return member(firm, Role.SENIOR_CA, "ca@example.test")


@pytest.fixture
def reader(firm):
    return member(firm, Role.READ_ONLY, "reader@example.test")


@pytest.fixture
def api(senior):
    """A signed-in senior CA. The role that can do everything in the pipeline."""
    return sign_in(senior.user)


@pytest.fixture
def staff_api(staff):
    return sign_in(staff.user)


@pytest.fixture
def statement(client_record):
    """An ingested, classified statement, ready for the review endpoints."""
    with firm_context(client_record.firm_id):
        result = ingest_fixture_statement(client_record)
        seed_client(client_record)
        classify_statement(result.statement)
        yield result.statement
