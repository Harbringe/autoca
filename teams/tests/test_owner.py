"""The firm owner, client settings, firm settings, and the audit log."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.models import AuditLog, FirmMembership, Role
from teams.models import TeamEvent

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]
V1 = "/api/v1"


def _owner(firm, email="owner@example.test"):
    m = member(firm, Role.FIRM_ADMIN, email)
    with firm_context(firm.pk):
        m.is_owner = True
        m.save(update_fields=["is_owner"])
    return m


@pytest.fixture
def owner(firm):
    return _owner(firm)


@pytest.fixture
def admin(firm):
    return member(firm, Role.FIRM_ADMIN, "admin@example.test")


# ---------------------------------------------------------------------------
# Owner
# ---------------------------------------------------------------------------


def test_only_the_owner_adds_or_removes_administrators(owner, admin, firm):
    other_admin = member(firm, Role.FIRM_ADMIN, "admin2@example.test")
    admin_http = sign_in(admin.user)

    invite = admin_http.post(f"{V1}/team/members/", {"email": "x@example.test", "role": Role.FIRM_ADMIN}, format="json")
    assert invite.status_code == 403
    assert admin_http.patch(f"{V1}/team/members/{other_admin.pk}/", {"is_active": False}, format="json").status_code == 403

    owner_http = sign_in(owner.user)
    assert owner_http.post(
        f"{V1}/team/members/", {"email": "x@example.test", "role": Role.FIRM_ADMIN}, format="json"
    ).status_code == 201
    assert owner_http.patch(
        f"{V1}/team/members/{other_admin.pk}/", {"role": Role.SENIOR_CA}, format="json"
    ).status_code == 200


def test_nobody_in_the_firm_can_remove_or_demote_the_owner(owner, admin):
    http = sign_in(admin.user)
    for body in ({"is_active": False}, {"role": Role.STAFF}):
        response = http.patch(f"{V1}/team/members/{owner.pk}/", body, format="json")
        assert response.status_code in {403, 409}
    owner.refresh_from_db()
    assert owner.is_active and owner.is_owner and owner.role == Role.FIRM_ADMIN


def test_admins_still_run_staff_and_senior_cas(owner, admin, firm):
    staff = member(firm, Role.STAFF, "s@example.test")
    http = sign_in(admin.user)
    assert http.patch(f"{V1}/team/members/{staff.pk}/", {"role": Role.SENIOR_CA}, format="json").status_code == 200
    assert http.post(f"{V1}/team/members/", {"email": "ca@example.test", "role": Role.SENIOR_CA}, format="json").status_code == 201


def test_ownership_transfers_to_an_administrator(owner, admin, firm):
    staff = member(firm, Role.STAFF, "s@example.test")
    http = sign_in(owner.user)

    assert http.post(f"{V1}/firm/owner/", {"member": str(staff.pk)}, format="json").status_code == 409
    assert sign_in(admin.user).post(f"{V1}/firm/owner/", {"member": str(admin.pk)}, format="json").status_code == 403

    moved = http.post(f"{V1}/firm/owner/", {"member": str(admin.pk)}, format="json")
    assert moved.status_code == 200, moved.content
    with firm_context(firm.pk):
        assert FirmMembership.objects.get(is_owner=True).pk == admin.pk
        assert FirmMembership.objects.get(pk=owner.pk).role == Role.FIRM_ADMIN
        assert TeamEvent.objects.filter(kind="firm.owner_changed").exists()


def test_a_firm_without_an_owner_behaves_as_before(admin, firm):
    other_admin = member(firm, Role.FIRM_ADMIN, "admin2@example.test")
    http = sign_in(admin.user)
    assert http.post(f"{V1}/team/members/", {"email": "x@example.test", "role": Role.FIRM_ADMIN}, format="json").status_code == 201
    assert http.post(f"{V1}/firm/owner/", {"member": str(other_admin.pk)}, format="json").status_code == 200


def test_session_says_who_the_owner_is(owner, admin):
    me = sign_in(owner.user).get(f"{V1}/me/").json()
    assert me["is_owner"] is True and me["role_display"] == "Firm owner"
    assert sign_in(admin.user).get(f"{V1}/me/").json()["is_owner"] is False


# ---------------------------------------------------------------------------
# Firm settings
# ---------------------------------------------------------------------------


def test_firm_settings_rename_and_details(owner, firm, senior):
    http = sign_in(owner.user)
    details = http.get(f"{V1}/firm/").json()
    assert details["owner"]["id"] == str(owner.pk)
    assert details["can"]["transfer"] is True

    assert http.patch(f"{V1}/firm/", {"name": "Renamed & Co"}, format="json").json()["name"] == "Renamed & Co"
    assert sign_in(senior.user).patch(f"{V1}/firm/", {"name": "Nope"}, format="json").status_code == 403


# ---------------------------------------------------------------------------
# Client settings
# ---------------------------------------------------------------------------


def test_only_owner_and_admins_edit_clients(owner, senior, staff, client_record):
    url = f"{V1}/clients/{client_record.pk}/"
    for person in (senior, staff):
        assert sign_in(person.user).patch(url, {"name": "Changed"}, format="json").status_code == 403
    response = sign_in(owner.user).patch(url, {"name": "Acme Traders Pvt Ltd"}, format="json")
    assert response.status_code == 200
    assert response.json()["name"] == "Acme Traders Pvt Ltd"


def test_client_edits_are_validated(owner, firm, client_record):
    from core.provisioning import create_client
    import datetime

    create_client(firm, "Other Client", datetime.date(2025, 4, 1))
    http = sign_in(owner.user)
    url = f"{V1}/clients/{client_record.pk}/"
    assert http.patch(url, {"name": "other client"}, format="json").status_code == 400
    assert http.patch(url, {"fy_start": "2025-07-15"}, format="json").status_code == 400
    assert http.post(f"{V1}/clients/", {"name": "OTHER CLIENT", "fy_start": "2025-04-01"}, format="json").status_code == 400


def test_a_client_with_posted_entries_cannot_be_deleted_or_move_its_year(owner, api, client_record, statement):
    api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    http = sign_in(owner.user)
    url = f"{V1}/clients/{client_record.pk}/"

    refused = http.delete(url)
    assert refused.status_code == 409
    assert "posted journal entr" in refused.json()["detail"]
    assert http.patch(url, {"fy_start": "2026-04-01"}, format="json").status_code == 400


def test_a_client_with_nothing_posted_can_be_deleted(owner, client_record):
    http = sign_in(owner.user)
    assert http.delete(f"{V1}/clients/{client_record.pk}/").status_code == 204
    assert http.get(f"{V1}/clients/{client_record.pk}/").status_code == 404


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_audit_log_reads_as_actions_and_is_for_owner_and_admins(owner, senior, client_record, firm):
    http = sign_in(owner.user)
    http.patch(f"{V1}/clients/{client_record.pk}/", {"name": "Acme Traders Pvt Ltd"}, format="json")
    with firm_context(firm.pk):
        assert AuditLog.objects.exists()

    page = http.get(f"{V1}/audit/?client={client_record.pk}").json()
    actions = [row["action"] for row in page["results"]]
    assert "Changed the details of Acme Traders Pvt Ltd" in actions

    mine = http.get(f"{V1}/audit/?user={owner.pk}").json()["results"]
    assert mine and all(row["email"] == owner.user.email for row in mine)

    assert sign_in(senior.user).get(f"{V1}/audit/").status_code == 403
