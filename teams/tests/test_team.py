"""Teams: invites, reporting lines, leads, assignments, deactivation, work counts."""

from __future__ import annotations

import datetime
import uuid

import pytest
from django.test import Client as HttpClient
from django.utils import timezone

from api.tests.conftest import PASSWORD, member, sign_in
from classify.models import LedgerAccount, TransactionClassification
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.models import ClientAssignment, FirmMembership, Role, User
from core.provisioning import create_firm
from teams.models import Invite, TeamEvent

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]
V1 = "/api/v1"
TEAM = f"{V1}/team"


@pytest.fixture
def admin(firm):
    return member(firm, Role.FIRM_ADMIN, "admin@example.test")


@pytest.fixture
def lead(firm):
    return member(firm, Role.SENIOR_CA, "asha@example.test")


@pytest.fixture
def other_lead(firm):
    return member(firm, Role.SENIOR_CA, "ravi@example.test")


def _on_team(firm, manager, email, role=Role.STAFF):
    m = member(firm, role, email)
    with firm_context(firm.pk):
        m.manager = manager
        m.scope_all_clients = False
        m.save(update_fields=["manager", "scope_all_clients"])
    return m


def _lead_client(client, lead):
    with firm_context(client.firm_id):
        client.lead = lead
        client.save(update_fields=["lead"])


def _accept(token, **body):
    http = HttpClient(enforce_csrf_checks=False)
    return http, http.post("/auth/invite/", {"token": token, **body}, content_type="application/json")


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def test_a_senior_ca_invites_staff_onto_their_own_team(lead):
    response = sign_in(lead.user).post(
        f"{TEAM}/members/", {"email": "New.Person@Example.test", "role": Role.STAFF}, format="json"
    )
    assert response.status_code == 201, response.content
    token = response.json()["link"].rsplit("/invite/", 1)[1]

    described = HttpClient().get("/auth/invite/", {"token": token}).json()
    assert described["email"] == "new.person@example.test"
    assert described["team"] == "asha@example.test"
    assert described["has_account"] is False

    http, accepted = _accept(token, full_name="New Person", password=PASSWORD)
    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["mfa"] == "setup"

    with firm_context(lead.firm_id):
        joined = FirmMembership.objects.get(user__email="new.person@example.test")
    assert joined.manager_id == lead.pk
    assert joined.role == Role.STAFF
    assert joined.scope_all_clients is False

    # Signed in with a password only: the API still demands a second factor.
    assert http.get(f"{V1}/me/").json()["code"] == "mfa_enrolment_required"

    _, again = _accept(token, full_name="New Person", password=PASSWORD)
    assert again.status_code == 410


def test_a_senior_ca_cannot_invite_a_senior_ca(lead):
    response = sign_in(lead.user).post(
        f"{TEAM}/members/", {"email": "x@example.test", "role": Role.SENIOR_CA}, format="json"
    )
    assert response.status_code == 403


def test_an_invitation_links_to_the_web_application(admin, lead, settings):
    settings.FRONTEND_URL = "https://app.example.test"
    response = sign_in(admin.user).post(
        f"{TEAM}/members/", {"email": "x@example.test", "manager": str(lead.pk)}, format="json"
    )
    assert response.json()["link"].startswith("https://app.example.test/invite/")


def test_staff_cannot_invite(firm, lead):
    staff = _on_team(firm, lead, "s@example.test")
    response = sign_in(staff.user).post(f"{TEAM}/members/", {"email": "x@example.test"}, format="json")
    assert response.status_code == 403


def test_an_invite_never_sets_an_existing_accounts_password(firm, admin, lead):
    existing = User.objects.create_user(email="known@example.test", password="the-real-password-1")
    token = sign_in(admin.user).post(
        f"{TEAM}/members/", {"email": "known@example.test", "role": Role.READ_ONLY, "manager": str(lead.pk)}, format="json"
    ).json()["link"].rsplit("/invite/", 1)[1]

    _, wrong = _accept(token, password="an-attackers-password-9")
    assert wrong.status_code == 401
    existing.refresh_from_db()
    assert existing.check_password("the-real-password-1")

    _, right = _accept(token, password="the-real-password-1")
    assert right.status_code == 200


def test_expired_revoked_and_forged_invites_are_refused(firm, admin, lead):
    http = sign_in(admin.user)
    body = http.post(f"{TEAM}/members/", {"email": "late@example.test", "manager": str(lead.pk)}, format="json").json()
    token = body["link"].rsplit("/invite/", 1)[1]

    with firm_context(firm.pk):
        Invite.objects.filter(pk=body["id"]).update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
    assert _accept(token, password=PASSWORD)[1].status_code == 410

    body = http.post(f"{TEAM}/members/", {"email": "late@example.test", "manager": str(lead.pk)}, format="json").json()
    assert http.delete(f"{TEAM}/invites/{body['id']}/").status_code == 204
    assert _accept(body["link"].rsplit("/invite/", 1)[1], password=PASSWORD)[1].status_code == 410

    forged = f"{uuid.uuid4()}.{token.split('.', 1)[1]}"
    assert _accept(forged, password=PASSWORD)[1].status_code == 404
    assert _accept("not-a-token", password=PASSWORD)[1].status_code == 404


def test_another_firms_member_cannot_be_named_as_manager(admin):
    other = create_firm("Other Firm")
    outsider = member(other, Role.SENIOR_CA, "outsider@example.test")
    response = sign_in(admin.user).post(
        f"{TEAM}/members/", {"email": "x@example.test", "manager": str(outsider.pk)}, format="json"
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Assignments and visibility
# ---------------------------------------------------------------------------


def test_a_lead_puts_their_staff_on_their_client(firm, client_record, lead):
    staff = _on_team(firm, lead, "s@example.test")
    _lead_client(client_record, lead)
    staff_http = sign_in(staff.user)
    assert staff_http.get(f"{V1}/clients/").json()["results"] == []

    response = sign_in(lead.user).post(
        f"{TEAM}/clients/{client_record.pk}/team/", {"member": str(staff.pk)}, format="json"
    )
    assert response.status_code == 201, response.content
    assert [c["name"] for c in staff_http.get(f"{V1}/clients/").json()["results"]] == ["Acme Traders"]

    assert sign_in(lead.user).delete(f"{TEAM}/clients/{client_record.pk}/team/{staff.pk}/").status_code == 204
    assert staff_http.get(f"{V1}/clients/").json()["results"] == []


def test_a_lead_cannot_assign_to_a_client_they_do_not_lead(firm, client_record, lead, other_lead):
    staff = _on_team(firm, lead, "s@example.test")
    _lead_client(client_record, other_lead)
    response = sign_in(lead.user).post(
        f"{TEAM}/clients/{client_record.pk}/team/", {"member": str(staff.pk)}, format="json"
    )
    assert response.status_code == 404


def test_a_lead_cannot_assign_someone_elses_staff(firm, client_record, lead, other_lead):
    theirs = _on_team(firm, other_lead, "theirs@example.test")
    _lead_client(client_record, lead)
    response = sign_in(lead.user).post(
        f"{TEAM}/clients/{client_record.pk}/team/", {"member": str(theirs.pk)}, format="json"
    )
    assert response.status_code == 403


def test_only_a_firm_admin_sets_a_clients_lead(client_record, admin, lead):
    url = f"{TEAM}/clients/{client_record.pk}/lead/"
    assert sign_in(lead.user).put(url, {"lead": str(lead.pk)}, format="json").status_code in {403, 404}
    response = sign_in(admin.user).put(url, {"lead": str(lead.pk)}, format="json")
    assert response.status_code == 200
    client_record.refresh_from_db()
    assert client_record.lead_id == lead.pk
    with firm_context(client_record.firm_id):
        assert TeamEvent.objects.filter(kind="client.lead_changed").exists()


def test_a_lead_sees_only_their_team(firm, lead, other_lead):
    mine = _on_team(firm, lead, "mine@example.test")
    _on_team(firm, other_lead, "theirs@example.test")
    emails = {m["email"] for m in sign_in(lead.user).get(f"{TEAM}/members/").json()["results"]}
    assert emails == {"asha@example.test", mine.user.email}


def test_staff_have_no_team_page(firm, lead):
    staff = _on_team(firm, lead, "s@example.test")
    assert sign_in(staff.user).get(f"{TEAM}/members/").status_code == 403


# ---------------------------------------------------------------------------
# Changing people
# ---------------------------------------------------------------------------


def test_a_lead_switches_their_own_team_off_and_on_but_nobody_elses(firm, lead, other_lead):
    mine = _on_team(firm, lead, "mine@example.test")
    theirs = _on_team(firm, other_lead, "theirs@example.test")
    http = sign_in(lead.user)

    assert http.patch(f"{TEAM}/members/{mine.pk}/", {"is_active": False}, format="json").status_code == 200
    assert sign_in(mine.user).get(f"{V1}/clients/").status_code == 403
    assert http.patch(f"{TEAM}/members/{mine.pk}/", {"is_active": True}, format="json").status_code == 200

    assert http.patch(f"{TEAM}/members/{theirs.pk}/", {"is_active": False}, format="json").status_code == 404
    assert http.patch(f"{TEAM}/members/{mine.pk}/", {"role": Role.SENIOR_CA}, format="json").status_code == 403


def test_a_lead_with_a_team_cannot_be_deactivated_until_handed_over(firm, admin, lead, other_lead):
    staff = _on_team(firm, lead, "s@example.test")
    http = sign_in(admin.user)

    refused = http.patch(f"{TEAM}/members/{lead.pk}/", {"is_active": False}, format="json")
    assert refused.status_code == 409
    assert "1 team member" in refused.json()["detail"]

    moved = http.patch(f"{TEAM}/members/{staff.pk}/", {"manager": str(other_lead.pk)}, format="json")
    assert moved.status_code == 200
    assert http.patch(f"{TEAM}/members/{lead.pk}/", {"is_active": False}, format="json").status_code == 200


def test_the_firm_always_keeps_an_administrator(firm, admin):
    http = sign_in(admin.user)
    response = http.patch(f"{TEAM}/members/{admin.pk}/", {"is_active": False}, format="json")
    assert response.status_code == 409


def test_moving_to_another_team_drops_the_old_leads_clients_unless_kept(firm, admin, client_record, lead, other_lead):
    staff = _on_team(firm, lead, "s@example.test")
    _lead_client(client_record, lead)
    with firm_context(firm.pk):
        ClientAssignment.objects.create(firm=firm, client=client_record, membership=staff)
    http = sign_in(admin.user)

    response = http.patch(
        f"{TEAM}/members/{staff.pk}/",
        {"manager": str(other_lead.pk), "keep_client_assignments": True},
        format="json",
    )
    assert response.status_code == 200
    with firm_context(firm.pk):
        assert ClientAssignment.objects.filter(membership=staff).count() == 1

    http.patch(f"{TEAM}/members/{staff.pk}/", {"manager": str(lead.pk)}, format="json")
    http.patch(f"{TEAM}/members/{staff.pk}/", {"manager": str(other_lead.pk)}, format="json")
    with firm_context(firm.pk):
        assert ClientAssignment.objects.filter(membership=staff).count() == 0


# ---------------------------------------------------------------------------
# Work
# ---------------------------------------------------------------------------


def test_work_counts_placement_by_the_preparer_and_approval_by_the_approver(
    firm, client_record, statement, lead
):
    staff = _on_team(firm, lead, "s@example.test")
    _lead_client(client_record, lead)
    with firm_context(firm.pk):
        ClientAssignment.objects.create(firm=firm, client=client_record, membership=staff)
        row = TransactionClassification.objects.filter(
            transaction__bank_account__client=client_record, ledger__isnull=True
        ).first()
        ledger = LedgerAccount.objects.filter(client=client_record, status="ACTIVE").exclude(
            name=row.transaction.bank_account.ledger_name
        ).first()

    placed = sign_in(staff.user).post(
        f"{V1}/classifications/{row.pk}/review/",
        {"ledger": str(ledger.pk), "rcm": False, "learn": False},
        format="json",
    )
    assert placed.status_code == 200, placed.content
    approved = sign_in(lead.user).post(
        f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json"
    )
    assert approved.status_code == 201

    lead_http = sign_in(lead.user)
    staff_work = lead_http.get(f"{TEAM}/members/{staff.pk}/work/").json()
    assert staff_work["totals"]["rows_placed"] == 1
    assert staff_work["totals"]["entries_approved"] == 0
    assert staff_work["open_work"][0]["name"] == "Acme Traders"

    lead_work = lead_http.get(f"{TEAM}/members/{lead.pk}/work/").json()
    assert lead_work["totals"]["entries_approved"] == len(approved.json())

    # Staff see their own work, not their lead's.
    assert sign_in(staff.user).get(f"{TEAM}/members/{staff.pk}/work/").status_code == 200
    assert sign_in(staff.user).get(f"{TEAM}/members/{lead.pk}/work/").status_code == 404


def test_history_records_who_changed_what(firm, admin, client_record, lead):
    staff = _on_team(firm, lead, "s@example.test")
    http = sign_in(admin.user)
    http.put(f"{TEAM}/clients/{client_record.pk}/lead/", {"lead": str(lead.pk)}, format="json")
    http.post(f"{TEAM}/clients/{client_record.pk}/team/", {"member": str(staff.pk)}, format="json")
    kinds = [e["kind"] for e in http.get(f"{TEAM}/events/").json()["results"]]
    assert kinds[:2] == ["client.assigned", "client.lead_changed"]


# ---------------------------------------------------------------------------
# A firm with no Senior CA: Staff and Read-only report to the owner or an administrator
# ---------------------------------------------------------------------------


def test_without_a_senior_ca_an_invite_defaults_to_the_owner_then_an_administrator(firm, admin):
    owner = member(firm, Role.FIRM_ADMIN, "owner@example.test")
    with firm_context(firm.pk):
        owner.is_owner = True
        owner.save(update_fields=["is_owner"])

    http = sign_in(admin.user)
    body = http.post(f"{TEAM}/members/", {"email": "a@example.test", "role": Role.STAFF}, format="json")
    assert body.status_code == 201, body.content
    _, accepted = _accept(body.json()["link"].rsplit("/invite/", 1)[1], full_name="A", password=PASSWORD)
    assert accepted.status_code == 200, accepted.content
    with firm_context(firm.pk):
        assert FirmMembership.objects.get(user__email="a@example.test").manager_id == owner.pk

    named = http.post(
        f"{TEAM}/members/", {"email": "b@example.test", "role": Role.READ_ONLY, "manager": str(admin.pk)}, format="json"
    )
    assert named.status_code == 201, named.content


def test_with_a_senior_ca_an_invite_cannot_point_at_an_administrator(firm, admin, lead):
    http = sign_in(admin.user)
    refused = http.post(
        f"{TEAM}/members/", {"email": "a@example.test", "role": Role.STAFF, "manager": str(admin.pk)}, format="json"
    )
    assert refused.status_code == 409
    assert http.post(f"{TEAM}/members/", {"email": "a@example.test", "role": Role.STAFF}, format="json").status_code == 409
    ok = http.post(
        f"{TEAM}/members/", {"email": "a@example.test", "role": Role.STAFF, "manager": str(lead.pk)}, format="json"
    )
    assert ok.status_code == 201


def test_an_administrator_moves_staff_under_an_administrator_only_while_there_is_no_senior_ca(firm, admin):
    other_admin = member(firm, Role.FIRM_ADMIN, "admin2@example.test")
    staff = member(firm, Role.STAFF, "s@example.test")
    http = sign_in(admin.user)
    url = f"{TEAM}/members/{staff.pk}/"

    assert http.patch(url, {"manager": str(other_admin.pk)}, format="json").status_code == 200
    with firm_context(firm.pk):
        assert FirmMembership.objects.get(pk=staff.pk).manager_id == other_admin.pk

    member(firm, Role.SENIOR_CA, "asha2@example.test")
    assert http.patch(url, {"manager": str(admin.pk)}, format="json").status_code == 409


def test_a_demoted_senior_ca_falls_back_to_an_administrator_when_no_senior_ca_is_left(firm, admin, lead):
    http = sign_in(admin.user)
    response = http.patch(f"{TEAM}/members/{lead.pk}/", {"role": Role.STAFF}, format="json")
    assert response.status_code == 200, response.content
    with firm_context(firm.pk):
        moved = FirmMembership.objects.get(pk=lead.pk)
    assert moved.role == Role.STAFF and moved.manager_id == admin.pk
