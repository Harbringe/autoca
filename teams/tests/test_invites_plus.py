"""Inviting people: the firm's limit on people, replacing and extending a link, several people at once, and email (off by default)."""

from __future__ import annotations

import datetime

import pytest
from django.test import Client as HttpClient
from django.utils import timezone

from api.tests.conftest import PASSWORD, member, sign_in
from core.db.session import firm_context
from core.models import FirmMembership, Role
from teams import mail, service
from teams.models import Invite, TeamEvent, TeamEventKind

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

TEAM = "/api/v1/team"


@pytest.fixture
def admin(firm):
    return member(firm, Role.FIRM_ADMIN, "admin@example.test")


@pytest.fixture
def lead(firm):
    return member(firm, Role.SENIOR_CA, "asha@example.test")


@pytest.fixture
def other_lead(firm):
    return member(firm, Role.SENIOR_CA, "ravi@example.test")


def accept(link, **body):
    token = link.rsplit("/invite/", 1)[1] if "/invite/" in link else link
    return HttpClient().post("/auth/invite/", {"token": token, **body}, content_type="application/json")


def invite(person, email, role=Role.STAFF):
    response = sign_in(person.user).post(f"{TEAM}/members/", {"email": email, "role": role}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


# ---------------------------------------------------------------------------
# The firm's limit on people
# ---------------------------------------------------------------------------


def test_a_firm_at_its_limit_cannot_invite_another_person(firm, lead):
    service.platform_set_limits(firm.pk, max_members=2)  # the lead, and one more
    invite(lead, "one@example.test")
    refused = sign_in(lead.user).post(f"{TEAM}/members/", {"email": "two@example.test", "role": Role.STAFF}, format="json")
    assert refused.status_code == 409
    assert "plan allows 2 people" in refused.json()["detail"]


def test_a_limit_counts_active_people_and_waiting_invitations_but_not_revoked_or_expired_ones(firm, lead):
    service.platform_set_limits(firm.pk, max_members=3)
    first = invite(lead, "one@example.test")
    second = invite(lead, "two@example.test")
    assert sign_in(lead.user).post(f"{TEAM}/members/", {"email": "three@example.test", "role": Role.STAFF}, format="json").status_code == 409

    assert sign_in(lead.user).delete(f"{TEAM}/invites/{first['id']}/").status_code == 204  # a revoked one frees its seat
    invite(lead, "three@example.test")
    with firm_context(firm.pk):
        Invite.objects.filter(pk=second["id"]).update(expires_at=timezone.now() - datetime.timedelta(minutes=1))  # an expired one too
    invite(lead, "four@example.test")


def test_accepting_is_refused_if_the_firm_filled_up_in_the_meantime(firm, admin, lead):
    service.platform_set_limits(firm.pk, max_members=3)  # admin, lead and the one invited
    waiting = invite(lead, "late@example.test")
    member(firm, Role.STAFF, "sneaked.in@example.test")  # added another way (the platform owner, say) while the invite was out
    refused = accept(waiting["link"], full_name="Late", password=PASSWORD)
    assert refused.status_code == 409
    assert "plan allows 3 people" in refused.json()["detail"]


def test_accepting_takes_the_seat_the_invitation_was_already_holding(firm, lead):
    service.platform_set_limits(firm.pk, max_members=2)
    waiting = invite(lead, "fits@example.test")
    assert accept(waiting["link"], full_name="Fits", password=PASSWORD).status_code == 200


def test_replacing_a_link_takes_no_extra_seat(firm, lead):
    service.platform_set_limits(firm.pk, max_members=2)
    waiting = invite(lead, "one@example.test")  # now full
    replaced = sign_in(lead.user).post(f"{TEAM}/invites/{waiting['id']}/regenerate/")
    assert replaced.status_code == 201, replaced.content


def test_no_limit_means_no_limit(firm, lead):
    for n in range(5):
        invite(lead, f"person{n}@example.test")


# ---------------------------------------------------------------------------
# Replacing and extending
# ---------------------------------------------------------------------------


def test_a_new_link_replaces_the_old_one(firm, lead):
    waiting = invite(lead, "newcomer@example.test")
    fresh = sign_in(lead.user).post(f"{TEAM}/invites/{waiting['id']}/regenerate/")
    assert fresh.status_code == 201
    body = fresh.json()
    assert body["link"] != waiting["link"] and body["email"] == "newcomer@example.test" and body["emailed"] is False
    assert accept(waiting["link"], full_name="N", password=PASSWORD).status_code == 410  # the old link no longer works
    assert accept(body["link"], full_name="N", password=PASSWORD).status_code == 200
    with firm_context(firm.pk):
        assert TeamEvent.objects.filter(kind=TeamEventKind.INVITE_REISSUED).count() == 1


def test_only_the_sender_or_an_administrator_may_replace_or_extend_a_link(firm, admin, lead, other_lead):
    waiting = invite(lead, "newcomer@example.test")
    stranger = sign_in(other_lead.user)
    assert stranger.get(f"{TEAM}/invites/").json()["results"] == []  # another Senior CA does not even see it
    assert stranger.post(f"{TEAM}/invites/{waiting['id']}/regenerate/").status_code == 404
    assert stranger.post(f"{TEAM}/invites/{waiting['id']}/extend/").status_code == 404
    assert sign_in(admin.user).post(f"{TEAM}/invites/{waiting['id']}/extend/").status_code == 200


def test_an_expired_invitation_stays_listed_for_a_month_and_can_get_a_new_link(firm, lead):
    waiting = invite(lead, "slow@example.test")
    with firm_context(firm.pk):
        Invite.objects.filter(pk=waiting["id"]).update(expires_at=timezone.now() - datetime.timedelta(days=2))
    listed = sign_in(lead.user).get(f"{TEAM}/invites/").json()["results"]
    assert [(i["email"], i["status"]) for i in listed] == [("slow@example.test", "expired")]
    assert sign_in(lead.user).post(f"{TEAM}/invites/{waiting['id']}/regenerate/").status_code == 201

    with firm_context(firm.pk):
        Invite.objects.filter(email="slow@example.test", used_at__isnull=True, revoked_at__isnull=True).update(
            expires_at=timezone.now() - datetime.timedelta(days=45)
        )
    assert sign_in(lead.user).get(f"{TEAM}/invites/").json()["results"] == []  # past a month, it drops off the list


def test_the_status_says_how_close_an_invitation_is_to_expiring(firm, lead):
    waiting = invite(lead, "soon@example.test")
    assert sign_in(lead.user).get(f"{TEAM}/invites/").json()["results"][0]["status"] == "pending"
    with firm_context(firm.pk):
        Invite.objects.filter(pk=waiting["id"]).update(expires_at=timezone.now() + datetime.timedelta(hours=10))
    assert sign_in(lead.user).get(f"{TEAM}/invites/").json()["results"][0]["status"] == "expiring_soon"


def test_extending_adds_a_week_but_never_more_than_thirty_days_after_it_was_made(firm, lead):
    waiting = invite(lead, "patient@example.test")
    http = sign_in(lead.user)
    first = http.post(f"{TEAM}/invites/{waiting['id']}/extend/")
    assert first.status_code == 200
    gained = datetime.datetime.fromisoformat(first.json()["expires_at"].replace("Z", "+00:00")) - datetime.datetime.fromisoformat(
        waiting["expires_at"].replace("Z", "+00:00")
    )
    assert gained == datetime.timedelta(days=7)
    for _ in range(4):  # 14, 21, 28 days, then up to the 30-day ceiling
        http.post(f"{TEAM}/invites/{waiting['id']}/extend/")
    with firm_context(firm.pk):
        record = Invite.objects.get(pk=waiting["id"])
        assert record.expires_at <= record.created_at + datetime.timedelta(days=30)
    refused = http.post(f"{TEAM}/invites/{waiting['id']}/extend/")
    assert refused.status_code == 409 and "too old to extend" in refused.json()["detail"]
    with firm_context(firm.pk):
        assert TeamEvent.objects.filter(kind=TeamEventKind.INVITE_EXTENDED).count() >= 1


def test_an_expired_invitation_is_extended_from_now_not_from_when_it_ran_out(firm, lead):
    waiting = invite(lead, "late@example.test")
    with firm_context(firm.pk):
        Invite.objects.filter(pk=waiting["id"]).update(expires_at=timezone.now() - datetime.timedelta(days=3))
    response = sign_in(lead.user).post(f"{TEAM}/invites/{waiting['id']}/extend/")
    assert response.status_code == 200 and response.json()["status"] == "pending"


# ---------------------------------------------------------------------------
# Several people at once
# ---------------------------------------------------------------------------


def test_several_people_are_invited_at_once_and_each_row_answers_for_itself(firm, admin, lead):
    rows = [
        {"email": "a@example.test", "role": Role.STAFF},
        {"email": "admin@example.test", "role": Role.STAFF},  # already in the firm
        {"email": "b@example.test", "full_name": "Bea", "role": Role.READ_ONLY},
    ]
    response = sign_in(lead.user).post(f"{TEAM}/members/bulk/", {"rows": rows}, format="json")
    assert response.status_code == 200, response.content
    results = response.json()["results"]
    assert [r["ok"] for r in results] == [True, False, True]
    assert "already in the firm" in results[1]["error"]
    assert accept(results[0]["link"], full_name="A", password=PASSWORD).status_code == 200  # the links work


def test_a_bulk_request_over_fifty_rows_or_with_no_rows_is_refused(firm, lead):
    http = sign_in(lead.user)
    assert http.post(f"{TEAM}/members/bulk/", {"rows": []}, format="json").status_code == 400
    many = [{"email": f"p{n}@example.test"} for n in range(51)]
    assert http.post(f"{TEAM}/members/bulk/", {"rows": many}, format="json").status_code == 400


def test_a_bulk_request_stops_at_the_firms_limit_and_the_rest_say_why(firm, lead):
    service.platform_set_limits(firm.pk, max_members=3)  # the lead and two more
    rows = [{"email": f"p{n}@example.test"} for n in range(4)]
    results = sign_in(lead.user).post(f"{TEAM}/members/bulk/", {"rows": rows}, format="json").json()["results"]
    assert [r["ok"] for r in results] == [True, True, False, False]
    assert "plan allows 3 people" in results[2]["error"]


def test_every_row_of_a_bulk_request_counts_against_the_senders_hourly_limit(firm, lead, settings):
    settings.THROTTLE_LIMITS = {**settings.THROTTLE_LIMITS, "invite_create": {"attempts": 2, "window_seconds": 3600, "lockout_seconds": 3600}}
    rows = [{"email": f"p{n}@example.test"} for n in range(4)]
    results = sign_in(lead.user).post(f"{TEAM}/members/bulk/", {"rows": rows}, format="json").json()["results"]
    assert [r["ok"] for r in results] == [True, True, False, False]
    assert "Too many invitations" in results[2]["error"]


def test_a_staff_member_cannot_invite_in_bulk(firm, lead):
    staff = member(firm, Role.STAFF, "staff@example.test")
    assert sign_in(staff.user).post(f"{TEAM}/members/bulk/", {"rows": [{"email": "x@example.test"}]}, format="json").status_code == 403


# ---------------------------------------------------------------------------
# Email (off unless the platform is set up for it)
# ---------------------------------------------------------------------------


def test_nothing_is_emailed_by_default_and_the_default_backend_is_not_the_console(settings, firm, lead):
    assert settings.INVITE_EMAIL_ENABLED is False
    assert "console" not in settings.EMAIL_BACKEND  # the console backend would print every link into the log
    assert invite(lead, "quiet@example.test")["emailed"] is False


def test_the_switch_alone_does_nothing_without_a_real_backend(settings):
    settings.INVITE_EMAIL_ENABLED = True
    for backend in ("django.core.mail.backends.dummy.EmailBackend", "django.core.mail.backends.console.EmailBackend", "django.core.mail.backends.locmem.EmailBackend"):
        settings.EMAIL_BACKEND = backend
        assert mail.enabled() is False


def test_an_invitation_is_emailed_when_enabled_with_a_real_backend(settings, firm, lead, monkeypatch):
    settings.INVITE_EMAIL_ENABLED = True
    settings.EMAIL_BACKEND = "anymail.backends.amazon_ses.EmailBackend"  # named only: sending is replaced below
    sent = []
    monkeypatch.setattr(mail, "send_mail", lambda subject, body, sender, to, fail_silently: sent.append((subject, body, to)) or 1)

    body = invite(lead, "mailed@example.test")
    assert body["emailed"] is True and len(sent) == 1
    subject, text, to = sent[0]
    assert to == ["mailed@example.test"] and body["link"] in text and "invited you" in subject


def test_a_mail_failure_does_not_block_the_invitation_or_leak_the_link(settings, firm, lead, monkeypatch, caplog):
    settings.INVITE_EMAIL_ENABLED = True
    settings.EMAIL_BACKEND = "anymail.backends.amazon_ses.EmailBackend"

    def boom(*args, **kwargs):
        raise ConnectionError("the mail service is down")

    monkeypatch.setattr(mail, "send_mail", boom)
    with caplog.at_level("DEBUG"):
        body = invite(lead, "unlucky@example.test")
    assert body["emailed"] is False and body["link"]  # still made; the link is shown by hand as before
    assert all(body["link"].rsplit("/invite/", 1)[1] not in record.getMessage() for record in caplog.records)


def test_the_email_text_names_the_firm_the_sender_and_the_role():
    subject, text = mail.render(firm_name="Sample & Co", inviter="Asha", role="Staff", url="https://example.test/invite/x", expires_days=7)
    assert "Asha" in subject and "Sample & Co" in subject
    assert "https://example.test/invite/x" in text and "7 days" in text and "Staff" in text


def test_members_invited_in_bulk_become_people_with_the_roles_they_were_given(firm, lead):
    rows = [{"email": "reader@example.test", "role": Role.READ_ONLY}]
    link = sign_in(lead.user).post(f"{TEAM}/members/bulk/", {"rows": rows}, format="json").json()["results"][0]["link"]
    assert accept(link, full_name="Rita Reader", password=PASSWORD).status_code == 200
    with firm_context(firm.pk):
        assert FirmMembership.objects.get(user__email="reader@example.test").role == Role.READ_ONLY
