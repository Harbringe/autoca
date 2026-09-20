"""A person belongs to one firm, and links inside a firm stay inside it.

These are the rules the Django admin's team pages write against. Until
``core/migrations/0009`` they lived in ``teams/service.py``, which every write
went through; a ModelAdmin form does not go through it. So they are asserted
here against the database itself, with ``full_clean`` bypassed, because that is
the only version of the rule a future code path cannot walk past.

The composite keys are DEFERRABLE INITIALLY DEFERRED so deleting a member, which
Django handles by nulling references mid-cascade, does not trip them. A test
transaction never commits, so each case asks for the check immediately.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import IntegrityError, connection, transaction

from core.db.session import firm_context
from core.models import Client, ClientAssignment, FirmMembership, Role, User
from core.provisioning import create_client, create_firm

pytestmark = pytest.mark.django_db


def _check_now():
    """Fire the deferred keys on the statement instead of at commit."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def _member(firm, email, role=Role.STAFF):
    user = User.objects.create_user(email=email, password="x" * 20)
    return FirmMembership.objects.create(firm_id=firm.pk, user=user, role=role)


@pytest.fixture
def two_firms():
    alpha = create_firm("Alpha & Co")
    beta = create_firm("Beta Associates")
    return alpha, beta


def test_an_account_belongs_to_one_firm(two_firms):
    """The rule that makes a profile page a single, complete answer."""
    alpha, beta = two_firms
    with firm_context(alpha.pk):
        person = _member(alpha, "shared@example.test").user

    with pytest.raises(IntegrityError):
        with firm_context(beta.pk), transaction.atomic():
            FirmMembership.objects.create(firm_id=beta.pk, user=person, role=Role.STAFF)


def test_a_member_cannot_report_to_another_firms_senior(two_firms):
    alpha, beta = two_firms
    with firm_context(alpha.pk):
        senior = _member(alpha, "senior@alpha.test", Role.SENIOR_CA)
    with firm_context(beta.pk):
        junior = _member(beta, "junior@beta.test")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _check_now()
                junior.manager = senior
                junior.save(update_fields=["manager"])


def test_a_client_cannot_be_led_by_another_firms_senior(two_firms):
    alpha, beta = two_firms
    with firm_context(alpha.pk):
        senior = _member(alpha, "lead@alpha.test", Role.SENIOR_CA)
    with firm_context(beta.pk):
        client = create_client(beta, "Beta Client", datetime.date(2026, 4, 1))

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _check_now()
                client.lead = senior
                client.save(update_fields=["lead"])


def test_a_member_cannot_be_assigned_another_firms_client(two_firms):
    alpha, beta = two_firms
    with firm_context(alpha.pk):
        alpha_client = create_client(alpha, "Alpha Client", datetime.date(2026, 4, 1))
    with firm_context(beta.pk):
        beta_member = _member(beta, "staff@beta.test")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _check_now()
                ClientAssignment.objects.create(
                    firm_id=beta.pk, client=alpha_client, membership=beta_member
                )


def test_the_ordinary_case_still_works(two_firms):
    """The guard must not break a firm working inside itself."""
    alpha, _beta = two_firms
    with firm_context(alpha.pk):
        senior = _member(alpha, "senior@ok.test", Role.SENIOR_CA)
        junior = _member(alpha, "junior@ok.test")
        junior.manager = senior
        junior.save(update_fields=["manager"])

        client = create_client(alpha, "Ok Client", datetime.date(2026, 4, 1))
        client.lead = senior
        client.save(update_fields=["lead"])

        ClientAssignment.objects.create(firm_id=alpha.pk, client=client, membership=junior)
        _check_now()

        # Reached without an IntegrityError, and the links point where they were
        # put rather than having been quietly dropped.
        assert Client.objects.get(pk=client.pk).lead_id == senior.pk
        assert FirmMembership.objects.get(pk=junior.pk).manager_id == senior.pk
        assert ClientAssignment.objects.filter(client=client, membership=junior).exists()
