"""Bringing a firm on board: the owner's invitation, replacing a link, limits, and the checklist."""

from __future__ import annotations

import datetime

import pytest
from django.test import Client as HttpClient
from django.utils import timezone

from api.tests.conftest import PASSWORD
from core.db.session import firm_context
from core.models import Firm, FirmMembership, Role
from core.provisioning import create_client, create_firm
from teams import service
from teams.models import Invite, TeamEvent, TeamEventKind

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def accept(link, **body):
    return HttpClient().post("/auth/invite/", {"token": link, **body}, content_type="application/json")


@pytest.fixture
def new_firm():
    return create_firm("Fresh Firm")


def test_the_owners_invitation_is_made_by_the_platform_and_lasts_two_weeks(new_firm):
    record, link = service.platform_invite_owner(new_firm.pk, email="  Owner@Fresh.TEST ", full_name="Oona Owner")
    assert record.email == "owner@fresh.test" and record.make_owner and record.role == Role.FIRM_ADMIN
    assert record.created_by_id is None
    assert datetime.timedelta(days=13) < record.expires_at - timezone.now() <= datetime.timedelta(days=14)
    assert link.startswith(f"{new_firm.pk}.")
    with firm_context(new_firm.pk):
        event = TeamEvent.objects.get(kind=TeamEventKind.INVITED)
        assert event.detail["actor"] == service.PLATFORM_ACTOR and event.detail["role"] == "Firm owner"


def test_accepting_the_owners_invitation_makes_them_the_owner_who_chooses_their_own_password(new_firm):
    _record, link = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test", full_name="Oona Owner")
    response = accept(link, full_name="Oona Owner", password=PASSWORD)
    assert response.status_code == 200, response.content
    with firm_context(new_firm.pk):
        owner = FirmMembership.objects.get(firm_id=new_firm.pk)
        assert owner.is_owner and owner.user.email == "owner@fresh.test"
        assert owner.user.check_password(PASSWORD)  # chosen by the person on accepting, never by the platform


def test_a_firm_with_an_owner_cannot_be_given_a_second_owner_invitation(new_firm):
    _record, link = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test")
    accept(link, password=PASSWORD, full_name="Oona")
    with pytest.raises(service.TeamError, match="already has an owner"):
        service.platform_invite_owner(new_firm.pk, email="another@fresh.test")


@pytest.mark.parametrize("bad", ["", "not an email", "a@b"])
def test_an_address_that_is_not_an_email_is_refused(new_firm, bad):
    with pytest.raises(service.TeamError, match="not an email"):
        service.platform_invite_owner(new_firm.pk, email=bad)


def test_a_new_link_replaces_the_old_one_which_stops_working(new_firm):
    first, old_link = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test")
    second, new_link = service.platform_reissue_invite(first.pk, new_firm.pk)
    assert new_link != old_link and second.pk != first.pk
    assert second.email == first.email and second.make_owner
    assert accept(old_link, password=PASSWORD, full_name="Oona").status_code == 410  # replaced
    assert accept(new_link, password=PASSWORD, full_name="Oona").status_code == 200
    with firm_context(new_firm.pk):
        assert TeamEvent.objects.filter(kind=TeamEventKind.INVITE_REISSUED).count() == 1


def test_a_used_invitation_cannot_be_replaced(new_firm):
    record, link = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test")
    accept(link, password=PASSWORD, full_name="Oona")
    with pytest.raises(service.TeamError, match="already been used"):
        service.platform_reissue_invite(record.pk, new_firm.pk)


def test_cancelling_the_invitation_stops_its_link_and_is_recorded(new_firm):
    record, link = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test")
    service.platform_revoke_invite(record.pk, new_firm.pk)
    assert accept(link, password=PASSWORD, full_name="Oona").status_code == 410
    service.platform_revoke_invite(record.pk, new_firm.pk)  # again: nothing happens, nothing breaks
    with firm_context(new_firm.pk):
        assert TeamEvent.objects.filter(kind=TeamEventKind.INVITE_REVOKED).count() == 1


def test_an_invitation_cannot_be_replaced_through_another_firms_context(new_firm):
    other = create_firm("Other Firm")
    record, _ = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test")
    with pytest.raises(service.TeamError, match="no longer exists"):
        service.platform_reissue_invite(record.pk, other.pk)


def test_the_checklist_follows_the_firm_from_invited_to_working(new_firm):
    state = service.platform_firm_onboarding(new_firm.pk)
    assert state["owner_invite"] == "none" and not state["owner_joined"]

    record, _link = service.platform_invite_owner(new_firm.pk, email="owner@fresh.test")
    state = service.platform_firm_onboarding(new_firm.pk)
    assert state["owner_invite"] == "pending" and state["owner_invite_id"] == str(record.pk)

    with firm_context(new_firm.pk):
        Invite.objects.filter(pk=record.pk).update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
    assert service.platform_firm_onboarding(new_firm.pk)["owner_invite"] == "expired"

    _, fresh = service.platform_reissue_invite(record.pk, new_firm.pk)
    accept(fresh, password=PASSWORD, full_name="Oona")
    state = service.platform_firm_onboarding(new_firm.pk)
    assert state["owner_invite"] == "accepted" and state["owner_joined"] and state["owner_email"] == "owner@fresh.test"
    assert state["owner_has_authenticator"] is False and state["clients"] == 0 and state["statements"] == 0

    create_client(new_firm, "First Client", datetime.date(2026, 4, 1))
    assert service.platform_firm_onboarding(new_firm.pk)["clients"] == 1


def test_limits_are_set_cleared_and_recorded(new_firm):
    after = service.platform_set_limits(
        new_firm.pk, max_members=5, max_clients=20, trial_ends_at=timezone.now() + datetime.timedelta(days=30), suspended_message="  Paused for payment.  "
    )
    assert after["max_members"] == 5 and after["suspended_message"] == "Paused for payment."
    limits = service.platform_firm_limits(new_firm.pk)
    assert limits["max_clients"] == 20 and limits["trial_ends_at"] is not None

    service.platform_set_limits(new_firm.pk)  # everything cleared: no limits, no trial, no message
    assert service.platform_firm_limits(new_firm.pk) == {"max_members": None, "max_clients": None, "trial_ends_at": None, "suspended_message": ""}
    with firm_context(new_firm.pk):
        events = TeamEvent.objects.filter(kind=TeamEventKind.FIRM_LIMITS_CHANGED)
        assert events.count() == 2 and all(e.detail["actor"] == service.PLATFORM_ACTOR for e in events)
    service.platform_set_limits(new_firm.pk)  # unchanged: no new event
    with firm_context(new_firm.pk):
        assert TeamEvent.objects.filter(kind=TeamEventKind.FIRM_LIMITS_CHANGED).count() == 2


@pytest.mark.parametrize("field", ["max_members", "max_clients"])
def test_a_limit_below_one_is_refused(new_firm, field):
    with pytest.raises(service.TeamError, match="at least 1"):
        service.platform_set_limits(new_firm.pk, **{field: 0})
    assert Firm.objects.filter(pk=new_firm.pk).exists()
