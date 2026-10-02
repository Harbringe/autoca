"""The platform owner changing where people work, from outside every firm.

There is no acting membership to check permissions against -- only the platform
owner reaches these, through the admin. What must still hold is everything that
protects a firm: it keeps an active administrator, nobody is left leading a team
or clients with nowhere to go, a team leader comes from the same firm, and an
account belongs to one firm.
"""

from __future__ import annotations

import datetime

import pytest

from api.tests.conftest import member
from core.db.session import firm_context
from core.models import FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from teams import service
from teams.models import TeamEvent, TeamEventKind
from teams.service import TeamError

pytestmark = pytest.mark.django_db


@pytest.fixture
def firm_a():
    firm = create_firm("Alpha & Co")
    member(firm, Role.FIRM_ADMIN, "admin@a.test")
    return firm


@pytest.fixture
def firm_b():
    return create_firm("Beta Associates")


def _person(email="person@example.test"):
    return User.objects.create_user(email=email, password="x" * 20)


def _events(firm, kind):
    with firm_context(firm.pk):
        return list(TeamEvent.objects.filter(kind=kind))


def test_assign_puts_someone_in_a_firm_and_records_it(firm_a):
    person = _person()
    joined = service.platform_assign(person, firm_a.pk, role=Role.SENIOR_CA)

    assert joined.role == Role.SENIOR_CA
    event = _events(firm_a, TeamEventKind.JOINED)[-1]
    assert event.detail["actor"] == service.PLATFORM_ACTOR
    assert event.actor_id is None


def test_an_account_joins_one_firm_only(firm_a, firm_b):
    member(firm_b, Role.FIRM_ADMIN, "admin@b.test")
    person = _person()
    service.platform_assign(person, firm_a.pk)
    with pytest.raises(TeamError, match="already belongs to a firm"):
        service.platform_assign(person, firm_b.pk)


def test_a_move_is_a_removal_and_a_join_in_one_transaction(firm_a, firm_b):
    """``firm_context`` clears itself on exit, so two firms fit in one transaction."""
    from django.db import transaction

    member(firm_b, Role.FIRM_ADMIN, "admin@b.test")
    person = _person()
    first = service.platform_assign(person, firm_a.pk)
    with transaction.atomic():
        service.platform_remove(first.pk, firm_a.pk)
        second = service.platform_assign(person, firm_b.pk)

    with firm_context(firm_b.pk):
        assert FirmMembership.objects.filter(pk=second.pk).exists()
    with firm_context(firm_a.pk):
        assert not FirmMembership.objects.filter(user=person).exists()
    assert _events(firm_a, TeamEventKind.REMOVED)


def test_a_manager_must_lead_in_the_same_firm(firm_a, firm_b):
    other_lead = member(firm_b, Role.SENIOR_CA, "lead@b.test")
    with pytest.raises(TeamError, match="active manager"):
        service.platform_assign(_person(), firm_a.pk, role=Role.STAFF, manager_id=other_lead.pk)


def test_a_senior_ca_reports_to_an_administrator_not_to_a_senior_ca(firm_a):
    lead = member(firm_a, Role.SENIOR_CA, "lead@a.test")
    with pytest.raises(TeamError, match="active manager"):
        service.platform_assign(_person(), firm_a.pk, role=Role.SENIOR_CA, manager_id=lead.pk)


def test_without_a_senior_ca_staff_report_to_the_owner_then_an_administrator(firm_a):
    with firm_context(firm_a.pk):
        first_admin = FirmMembership.objects.get(role=Role.FIRM_ADMIN)
    owner = member(firm_a, Role.FIRM_ADMIN, "owner@a.test")
    with firm_context(firm_a.pk):
        owner.is_owner = True
        owner.save(update_fields=["is_owner"])

    by_default = service.platform_assign(_person("one@example.test"), firm_a.pk, role=Role.STAFF)
    assert by_default.manager_id == owner.pk
    named = service.platform_assign(
        _person("two@example.test"), firm_a.pk, role=Role.READ_ONLY, manager_id=first_admin.pk
    )
    assert named.manager_id == first_admin.pk


def test_with_a_senior_ca_staff_may_not_report_to_an_administrator(firm_a):
    with firm_context(firm_a.pk):
        admin = FirmMembership.objects.get(role=Role.FIRM_ADMIN)
    member(firm_a, Role.SENIOR_CA, "lead@a.test")

    with pytest.raises(TeamError, match="active manager"):
        service.platform_assign(_person("x@example.test"), firm_a.pk, role=Role.STAFF, manager_id=admin.pk)
    with pytest.raises(TeamError, match="active manager"):
        service.platform_assign(_person("y@example.test"), firm_a.pk, role=Role.STAFF)


def test_the_fallback_manager_must_be_active(firm_a):
    with firm_context(firm_a.pk):
        admin = FirmMembership.objects.get(role=Role.FIRM_ADMIN)
        admin.is_active = False
        admin.save(update_fields=["is_active"])
    with pytest.raises(TeamError, match="active manager"):
        service.platform_assign(_person(), firm_a.pk, role=Role.STAFF, manager_id=admin.pk)


def test_the_last_administrator_cannot_be_removed_or_demoted(firm_a):
    with firm_context(firm_a.pk):
        admin = FirmMembership.objects.get(role=Role.FIRM_ADMIN)

    with pytest.raises(TeamError, match="at least one active firm administrator"):
        service.platform_remove(admin.pk, firm_a.pk)
    with pytest.raises(TeamError, match="at least one active firm administrator"):
        service.platform_update(
            admin.pk, firm_a.pk, role=Role.STAFF, manager_id=None,
            scope_all_clients=True, is_active=True, make_owner=False,
        )


def test_the_owner_cannot_be_removed_or_stepped_down(firm_a):
    second = member(firm_a, Role.FIRM_ADMIN, "second@a.test")
    service.platform_update(
        second.pk, firm_a.pk, role=Role.FIRM_ADMIN, manager_id=None,
        scope_all_clients=True, is_active=True, make_owner=True,
    )

    with pytest.raises(TeamError, match="owner"):
        service.platform_remove(second.pk, firm_a.pk)
    with pytest.raises(TeamError, match="owner"):
        service.platform_update(
            second.pk, firm_a.pk, role=Role.FIRM_ADMIN, manager_id=None,
            scope_all_clients=True, is_active=False, make_owner=True,
        )


def test_a_lead_with_a_team_or_clients_cannot_leave(firm_a):
    lead = member(firm_a, Role.SENIOR_CA, "lead@a.test")
    with firm_context(firm_a.pk):
        client = create_client(firm_a, "Vasant Traders", datetime.date(2026, 4, 1))
        client.lead = lead
        client.save(update_fields=["lead"])

    with pytest.raises(TeamError, match="still leads"):
        service.platform_remove(lead.pk, firm_a.pk)
    with pytest.raises(TeamError, match="still leads"):
        service.platform_update(
            lead.pk, firm_a.pk, role=Role.STAFF, manager_id=None,
            scope_all_clients=False, is_active=True, make_owner=False,
        )


def test_update_records_each_change(firm_a):
    lead = member(firm_a, Role.SENIOR_CA, "lead@a.test")
    staff = member(firm_a, Role.STAFF, "staff@a.test")

    service.platform_update(
        staff.pk, firm_a.pk, role=Role.STAFF, manager_id=lead.pk,
        scope_all_clients=False, is_active=True, make_owner=False,
    )

    with firm_context(firm_a.pk):
        staff.refresh_from_db()
        assert staff.manager_id == lead.pk
        assert staff.scope_all_clients is False
    assert _events(firm_a, TeamEventKind.MANAGER_CHANGED)
    assert _events(firm_a, TeamEventKind.SCOPE_CHANGED)


def test_a_firm_is_renamed_from_outside_it(firm_a):
    service.platform_update_firm(firm_a.pk, name="Alpha Partners", is_active=True)
    with firm_context(firm_a.pk):
        firm_a.refresh_from_db()
    assert firm_a.name == "Alpha Partners"
    assert _events(firm_a, TeamEventKind.FIRM_RENAMED)[-1].detail["actor"] == service.PLATFORM_ACTOR
