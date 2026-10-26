"""What the platform owner agrees with a firm: a limit on clients, a message when it is switched off, and a notice about the trial."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from api.tests.conftest import member, sign_in
from core.models import Role
from teams import service

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def new_client(http, name):
    return http.post(f"{V1}/clients/", {"name": name, "fy_start": "2026-04-01"}, format="json")


def test_a_firm_at_its_client_limit_cannot_add_another(api, firm):
    service.platform_set_limits(firm.pk, max_clients=1)
    assert new_client(api, "First").status_code == 201
    refused = new_client(api, "Second")
    assert refused.status_code == 409
    assert "plan allows 1 client." in refused.json()["detail"]


def test_a_larger_limit_allows_up_to_it_and_no_limit_allows_any_number(api, firm):
    service.platform_set_limits(firm.pk, max_clients=2)
    assert [new_client(api, f"C{n}").status_code for n in range(3)] == [201, 201, 409]
    service.platform_set_limits(firm.pk)  # cleared
    assert new_client(api, "Another").status_code == 201


def test_raising_the_limit_lets_the_firm_carry_on(api, firm):
    service.platform_set_limits(firm.pk, max_clients=1)
    new_client(api, "First")
    assert new_client(api, "Second").status_code == 409
    service.platform_set_limits(firm.pk, max_clients=5)
    assert new_client(api, "Second").status_code == 201


def test_a_switched_off_firm_tells_its_people_why(firm):
    person = member(firm, Role.STAFF, "staff@example.test")
    service.platform_set_limits(firm.pk, suspended_message="Paused until the invoice is settled. Write to billing@example.test.")
    service.platform_update_firm(firm.pk, name=firm.name, is_active=False)
    refused = sign_in(person.user).get(f"{V1}/me/")
    assert refused.status_code == 403
    assert refused.json() == {"code": "firm_inactive", "detail": "Paused until the invoice is settled. Write to billing@example.test."}


def test_without_a_message_the_default_words_are_used(firm):
    person = member(firm, Role.STAFF, "staff@example.test")
    service.platform_update_firm(firm.pk, name=firm.name, is_active=False)
    assert sign_in(person.user).get(f"{V1}/me/").json()["detail"] == "This firm has been deactivated."


def test_only_a_firm_administrator_is_told_about_the_trial_and_only_when_it_is_close(firm):
    admin = member(firm, Role.FIRM_ADMIN, "admin@example.test")
    staff = member(firm, Role.STAFF, "staff@example.test")
    now = timezone.now()

    def notice(person):
        return sign_in(person.user).get(f"{V1}/me/").json()["trial"]

    service.platform_set_limits(firm.pk, trial_ends_at=now + datetime.timedelta(days=5))
    assert notice(admin)["days_left"] in (4, 5) and notice(staff) is None

    service.platform_set_limits(firm.pk, trial_ends_at=now + datetime.timedelta(days=60))
    assert notice(admin) is None  # far off: nothing to say yet

    service.platform_set_limits(firm.pk, trial_ends_at=now - datetime.timedelta(days=3))
    assert notice(admin)["days_left"] < 0  # just ended: still told

    service.platform_set_limits(firm.pk, trial_ends_at=now - datetime.timedelta(days=40))
    assert notice(admin) is None

    service.platform_set_limits(firm.pk)
    assert notice(admin) is None  # no trial at all
