"""Approving and sealing, from the outside."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def test_the_status_carries_the_schedule_and_no_approval_for_a_new_client(api, client_record):
    body = api.get(f"{base(client_record)}/books/").json()

    assert body["close_period"] == "QUARTERLY" and body["approved_through"] is None
    assert body["sealable_dates"] == [] and body["changed_since_approval"] == 0
    assert body["next_seal_date"]


def test_sealing_with_no_approval_is_refused_with_a_code(api, client_record):
    response = api.post(f"{base(client_record)}/books/sign-off/", {}, format="json")

    assert response.status_code == 409 and response.json()["code"] == "approval_needed"


def test_approving_nothing_that_was_requested_is_refused(api, client_record):
    response = api.post(f"{base(client_record)}/books/approve/", {}, format="json")

    assert response.status_code == 409


@pytest.fixture
def admin_api(firm):
    from api.tests.conftest import member, sign_in
    from core.models import Role

    return sign_in(member(firm, Role.FIRM_ADMIN, "admin@example.test").user)


def test_the_schedule_can_be_changed_by_a_firm_administrator(api, admin_api, client_record):
    response = admin_api.patch(f"/api/v1/clients/{client_record.pk}/", {"close_period": "YEARLY"}, format="json")

    assert response.status_code == 200 and response.json()["close_period"] == "YEARLY"
    assert api.get(f"{base(client_record)}/books/").json()["close_period"] == "YEARLY"


def test_an_unknown_schedule_is_a_400(admin_api, client_record):
    response = admin_api.patch(f"/api/v1/clients/{client_record.pk}/", {"close_period": "WEEKLY"}, format="json")

    assert response.status_code == 400


def test_staff_cannot_approve(client_record, staff_api):
    assert staff_api.post(f"{base(client_record)}/books/approve/", {}, format="json").status_code == 403
