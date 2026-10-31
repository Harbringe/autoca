"""The platform dashboard and the invitations of every firm: what the views return, to whom, and what the admin does with them."""

from __future__ import annotations

import datetime

import pytest
from django.test import Client as HttpClient
from django.utils import timezone

from api.tests.conftest import PASSWORD, member, sign_in
from core.db.session import firm_context
from core.models import Role
from core.provisioning import create_client
from superadmin import sql
from superadmin.models import PlatformFirmStats, PlatformInvite
from superadmin.tests.test_superadmin import (  # noqa: F401
    firm_a,
    firm_b,
    operator,
    reading_as,
    views,
)
from teams import service
from teams.models import Invite

pytestmark = pytest.mark.django_db

INVITES = "/admin/superadmin/platforminvite/"
DASHBOARD = "/admin/superadmin/platformfirmstats/"


def owner_invite(firm, email="o@example.test"):
    return service.platform_invite_owner(firm.pk, email=email, full_name="Olive")


# ---------------------------------------------------------------------------
# The SQL, as text (runs wherever the suite runs)
# ---------------------------------------------------------------------------


def test_the_new_views_are_part_of_the_installed_set_and_read_only_gated():
    assert "app.platform_invites" in sql.VIEWS and "app.platform_firm_stats" in sql.VIEWS
    assert "teams_invite" in sql.TABLES
    for view in ("platform_invites", "platform_firm_stats"):
        block = sql.VIEWS_SQL.split(f"CREATE VIEW app.{view}", 1)[1].split("CREATE VIEW", 1)[0]
        assert "WITH (security_barrier = true)" in sql.VIEWS_SQL.split(f"CREATE VIEW app.{view}", 1)[1][:80]
        assert "WHERE app.superadmin_can_read()" in block


@pytest.mark.parametrize("model", [PlatformInvite, PlatformFirmStats])
def test_every_column_the_model_expects_is_selected_by_its_view(model):
    view = model._meta.db_table.split('"."')[1]
    block = sql.VIEWS_SQL.split(f"CREATE VIEW app.{view}", 1)[1].split("CREATE VIEW", 1)[0]
    for field in model._meta.fields:
        assert field.column in block, f"{view} does not select {field.column}"


def test_the_invitation_view_never_carries_the_link_or_its_hash():
    block = sql.VIEWS_SQL.split("CREATE VIEW app.platform_invites", 1)[1].split("CREATE VIEW", 1)[0]
    assert "token" not in block


# ---------------------------------------------------------------------------
# What the views return
# ---------------------------------------------------------------------------


def test_the_platform_owner_sees_every_firms_invitations_with_where_each_stands(views, operator, firm_a, firm_b):
    pending, _ = owner_invite(firm_a, "pending@example.test")
    expired, _ = owner_invite(firm_b, "expired@example.test")
    revoked, _ = owner_invite(firm_b, "revoked@example.test")
    with firm_context(firm_b.pk):
        Invite.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - datetime.timedelta(days=1))
        Invite.objects.filter(pk=revoked.pk).update(revoked_at=timezone.now())
    _, link = owner_invite(firm_a, "accepted@example.test")
    HttpClient().post("/auth/invite/", {"token": link, "full_name": "Olive", "password": PASSWORD}, content_type="application/json")

    with reading_as(operator):
        states = {i.email: i.state for i in PlatformInvite.objects.all()}
    assert states["expired@example.test"] == "expired"
    assert states["revoked@example.test"] == "revoked"
    assert states["accepted@example.test"] == "accepted"
    assert states["pending@example.test"] == "pending"


def test_nobody_but_the_platform_owner_reads_the_invitations_or_the_dashboard(views, firm_a):
    person = member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    owner_invite(firm_a)
    with reading_as(person.user):
        assert PlatformInvite.objects.count() == 0
        assert PlatformFirmStats.objects.count() == 0


def test_the_dashboard_counts_people_clients_and_invitations_and_carries_what_is_agreed(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    member(firm_a, Role.STAFF, "staff@a.test")
    with firm_context(firm_a.pk):
        create_client(firm_a, "Client One", datetime.date(2026, 4, 1))
    owner_invite(firm_b)
    service.platform_set_limits(firm_a.pk, max_members=2, max_clients=10, trial_ends_at=timezone.now() + datetime.timedelta(days=3))

    with reading_as(operator):
        stats = {s.name: s for s in PlatformFirmStats.objects.all()}
    a, b = stats["Alpha & Co"], stats["Beta Associates"]
    assert (a.active_members, a.clients, a.pending_invites, a.max_members, a.max_clients) == (2, 1, 0, 2, 10)
    assert a.trial_ends_at is not None and a.last_activity is None and a.failed_jobs_30d == 0
    assert (b.active_members, b.pending_invites, b.clients, b.max_members) == (0, 1, 0, None)


# ---------------------------------------------------------------------------
# The admin pages and what they do
# ---------------------------------------------------------------------------


def test_the_invitation_and_dashboard_pages_open_and_list_what_is_there(views, operator, firm_a):
    owner_invite(firm_a, "listed@example.test")
    http = sign_in(operator)
    page = http.get(INVITES)
    assert page.status_code == 200 and "listed@example.test" in page.content.decode()
    assert "Alpha &amp; Co" in http.get(DASHBOARD).content.decode()
    assert http.get(f"{INVITES}add/").status_code == 403  # read-only


def test_the_dashboard_filters_pick_out_the_firms_that_need_attention(views, operator, firm_a, firm_b):
    service.platform_set_limits(firm_a.pk, trial_ends_at=timezone.now() + datetime.timedelta(days=2))
    owner_invite(firm_b)
    http = sign_in(operator)
    trial = http.get(DASHBOARD, {"flag": "trial"}).content.decode()
    assert "Alpha &amp; Co" in trial and "Beta Associates" not in trial
    nobody = http.get(DASHBOARD, {"flag": "no_owner"}).content.decode()
    assert "Alpha &amp; Co" in nobody and "Beta Associates" in nobody  # neither has an owner who joined
    quiet = http.get(DASHBOARD, {"flag": "quiet"}).content.decode()
    assert "Alpha &amp; Co" in quiet  # nothing has happened there at all
    assert http.get(DASHBOARD, {"flag": "full"}).status_code == 200 and http.get(DASHBOARD, {"flag": "failing"}).status_code == 200


def test_a_new_link_for_selected_invitations_is_shown_once_and_the_old_link_stops_working(views, operator, firm_a):
    record, old_link = owner_invite(firm_a, "stuck@example.test")
    http = sign_in(operator)
    done = http.post(INVITES, {"action": "new_links", "_selected_action": [str(record.pk)], "index": "0"})
    assert done.status_code == 302 and done["Location"].endswith("/links/")
    page = http.get(done["Location"]).content.decode()
    assert "stuck@example.test" in page and "/invite/" in page
    assert "/invite/" not in http.get(done["Location"]).content.decode()  # shown once

    stale = HttpClient().post("/auth/invite/", {"token": old_link, "full_name": "X", "password": PASSWORD}, content_type="application/json")
    assert stale.status_code == 410


def test_cancelling_selected_invitations_stops_their_links(views, operator, firm_a):
    record, link = owner_invite(firm_a, "cancel@example.test")
    http = sign_in(operator)
    assert http.post(INVITES, {"action": "cancel", "_selected_action": [str(record.pk)], "index": "0"}).status_code == 302
    stale = HttpClient().post("/auth/invite/", {"token": link, "full_name": "X", "password": PASSWORD}, content_type="application/json")
    assert stale.status_code == 410
