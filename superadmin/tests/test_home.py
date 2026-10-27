"""The platform owner's home page and the look of the admin: what the page shows, to whom, and that nothing third-party loads."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from superadmin.tests.test_superadmin import (  # noqa: F401
    firm_a,
    firm_b,
    operator,
    views,
)

pytestmark = pytest.mark.django_db


def test_the_admin_loads_the_platform_stylesheet_and_no_third_party_fonts(views, operator):
    page = sign_in(operator).get("/admin/").content.decode()
    assert "superadmin/platform.css" in page
    assert "fonts.googleapis.com" not in page


# ---------------------------------------------------------------------------
# The numbers behind the home page
# ---------------------------------------------------------------------------

import datetime  # noqa: E402

from django.utils import timezone  # noqa: E402

from api.tests.conftest import member  # noqa: E402
from core.db.session import firm_context  # noqa: E402
from core.models import AuditLog, Firm, Job, Role  # noqa: E402
from core.provisioning import create_client, create_firm  # noqa: E402
from superadmin.home import ROW_LIMIT, build_home  # noqa: E402
from superadmin.tests.test_superadmin import reading_as  # noqa: E402
from teams import service  # noqa: E402


def _home(operator, **kwargs):
    with reading_as(operator):
        return build_home(timezone.now(), **kwargs)


def _age(firm, days):
    with firm_context(firm.pk):
        Firm.objects.filter(pk=firm.pk).update(created_at=timezone.now() - datetime.timedelta(days=days))


def test_an_empty_platform_gives_zeros_and_no_rows(views, operator):
    home = _home(operator)
    assert home.total_firms == 0 and home.rows == [] and home.attention == []
    assert [k.value for k in home.kpis] == ["0", "0", "0", "-", "0"]


def test_a_trial_that_ended_raises_one_item_with_its_words(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    service.platform_set_limits(firm_a.pk, trial_ends_at=timezone.now() - datetime.timedelta(days=3))
    home = _home(operator)
    assert [(a.firm_name, a.tone, a.action_label) for a in home.attention] == [("Alpha & Co", "bad", "Extend trial")]
    assert home.attention[0].what == "Trial ended 3 days ago and the firm is still in service."
    assert home.rows[0].status == "Trial ended"


def test_a_failed_job_a_full_firm_and_a_stuck_invite_each_raise_an_item(views, operator, firm_a, firm_b):
    admin = member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    with firm_context(firm_a.pk):
        Job.objects.create(firm=firm_a, kind="statement.ingest", status="FAILED", created_by=admin.user)
    service.platform_set_limits(firm_a.pk, max_members=1)
    _, _link = service.platform_invite_owner(firm_b.pk, email="o@b.test", full_name="Olive")
    with firm_context(firm_b.pk):
        from teams.models import Invite

        Invite.objects.filter(firm_id=firm_b.pk).update(created_at=timezone.now() - datetime.timedelta(days=9))
    home = _home(operator)
    labels = sorted((a.firm_name, a.action_label) for a in home.attention)
    assert labels == [("Alpha & Co", "Open jobs"), ("Alpha & Co", "Raise limit"), ("Beta Associates", "New link")]
    assert home.attention[0].firm_name == "Beta Associates"  # oldest first


def test_a_quiet_firm_is_flagged_but_a_new_one_is_not(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    member(firm_b, Role.FIRM_ADMIN, "admin@b.test")
    _age(firm_a, 40)
    home = _home(operator)
    assert [(a.firm_name, a.action_label) for a in home.attention] == [("Alpha & Co", "Check in")]


def test_a_healthy_firm_raises_nothing(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    with firm_context(firm_a.pk):
        AuditLog.objects.create(firm=firm_a, method="GET", path="/x", status_code=200)
    home = _home(operator)
    assert home.attention == [] and home.rows[0].status == "Active" and home.rows[0].tone == "good"


def test_a_firm_without_limits_shows_the_count_alone(views, operator, firm_a):
    member(firm_a, Role.STAFF, "staff@a.test")
    with firm_context(firm_a.pk):
        create_client(firm_a, "Client One", datetime.date(2026, 4, 1))
    row = _home(operator).rows[0]
    assert (row.people_text, row.people_pct, row.clients_text, row.clients_pct) == ("1", None, "1", None)


def test_a_limit_gives_a_text_a_rounded_percentage_and_a_bar_state(views, operator, firm_a):
    for n in range(4):
        member(firm_a, Role.STAFF, f"s{n}@a.test")
    service.platform_set_limits(firm_a.pk, max_members=5, max_clients=50)
    row = _home(operator).rows[0]
    assert (row.people_text, row.people_pct, row.people_state) == ("4 of 5", 80, "near")
    assert (row.clients_text, row.clients_pct, row.clients_state) == ("0 of 50", 0, "")


def test_rows_stop_at_the_limit_and_report_the_total(views, operator):
    for n in range(ROW_LIMIT + 2):
        create_firm(f"Firm {n:03d}")
    home = _home(operator)
    assert len(home.rows) == ROW_LIMIT and home.shown_firms == ROW_LIMIT + 2 and home.total_firms == ROW_LIMIT + 2


def test_a_tab_narrows_the_table_and_counts_every_tab(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    service.platform_set_limits(firm_a.pk, trial_ends_at=timezone.now() - datetime.timedelta(days=1))
    member(firm_b, Role.FIRM_ADMIN, "admin@b.test")
    with firm_context(firm_b.pk):
        AuditLog.objects.create(firm=firm_b, method="GET", path="/x", status_code=200)
    only = _home(operator, tab="attention")
    assert [r.name for r in only.rows] == ["Alpha & Co"]
    assert only.tab_counts == {"all": 2, "attention": 1, "trial": 1, "healthy": 1}


def test_an_unknown_tab_is_treated_as_all(views, operator, firm_a):
    assert _home(operator, tab="nonsense").tab == "all"


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_home_shows_the_numbers_the_attention_list_and_every_firm(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    service.platform_set_limits(firm_a.pk, trial_ends_at=timezone.now() - datetime.timedelta(days=3))
    page = sign_in(operator).get("/admin/").content.decode()
    assert "Needs you today" in page and "Extend trial" in page
    assert "Alpha &amp; Co" in page and "Beta Associates" in page
    assert "Add a firm" in page and "Trial ended" in page


def test_a_tab_narrows_the_page(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    service.platform_set_limits(firm_a.pk, trial_ends_at=timezone.now() - datetime.timedelta(days=3))
    member(firm_b, Role.FIRM_ADMIN, "admin@b.test")
    with firm_context(firm_b.pk):
        AuditLog.objects.create(firm=firm_b, method="GET", path="/x", status_code=200)
    http = sign_in(operator)
    page = http.get("/admin/", {"tab": "healthy"}).content.decode()
    table = page.split("All firms", 1)[1].split("Model spend by firm", 1)[0]
    assert "Beta Associates" in table and "Alpha &amp; Co" not in table


def test_a_firm_name_is_escaped_on_home(views, operator):
    create_firm("<b>x</b> & Co")
    page = sign_in(operator).get("/admin/").content.decode()
    assert "&lt;b&gt;x&lt;/b&gt; &amp; Co" in page and "<b>x</b>" not in page


def test_an_empty_platform_invites_the_first_firm(views, operator):
    page = sign_in(operator).get("/admin/").content.decode()
    assert "Add your first firm" in page and "Nothing needs you today." in page


def test_a_firm_administrator_cannot_open_the_admin(views, firm_a):
    person = member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    response = sign_in(person.user).get("/admin/")
    assert response.status_code in (302, 403) and "Needs you today" not in response.content.decode()
