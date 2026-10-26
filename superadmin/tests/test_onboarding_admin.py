"""The firm page of the platform admin, exercised without the cross-firm views (which a test database may not have).

``test_superadmin.py`` drives the same pages end to end where those views exist. These call the admin's own pieces directly, so the
onboarding behaviour is checked everywhere the suite runs: the add form, what saving it does, and the buttons for the owner's link.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.loader import get_template
from django.test import RequestFactory
from django.utils import timezone

from core.db.session import firm_context
from core.models import User
from core.provisioning import create_firm
from superadmin.admin import FirmForm, PlatformFirmAdmin
from superadmin.models import PlatformFirm
from teams import service
from teams.models import Invite

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator():
    return User.objects.create_user(email="operator@example.test", password="x" * 20, is_superuser=True, is_staff=True)


@pytest.fixture
def page():
    return PlatformFirmAdmin(PlatformFirm, AdminSite())


@pytest.fixture
def request_for(operator):
    def make(data=None):
        request = RequestFactory().post("/admin/superadmin/platformfirm/", data or {})
        request.user = operator
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    return make


def add_form(**over):
    data = {"name": "Added Co", "owner_name": "Olive Owner", "owner_email": "olive@added.test", "is_active": "on", **over}
    return FirmForm(data=data, instance=PlatformFirm())


def test_adding_a_firm_needs_the_owners_email_and_a_name():
    assert add_form().is_valid()
    assert "owner_email" in add_form(owner_email="").errors
    assert "name" in add_form(name=" x ").errors
    assert "owner_email" in add_form(owner_email="not-an-email").errors


def test_the_limits_must_be_positive_and_the_trial_date_becomes_the_end_of_that_day():
    assert "max_members" in add_form(max_members="0").errors
    assert "max_clients" in add_form(max_clients="-3").errors
    form = add_form(trial_ends_on="2026-12-31")
    assert form.is_valid()
    end = form.trial_end()
    assert timezone.is_aware(end) and (end.year, end.month, end.day, end.hour) == (2026, 12, 31, 23)
    assert add_form().trial_end() is None


def test_saving_the_add_form_makes_the_firm_invites_its_owner_and_keeps_the_link_for_one_view(page, request_for):
    request = request_for()
    form = add_form(max_members="5", max_clients="20")
    assert form.is_valid(), form.errors
    obj = PlatformFirm()
    page.save_model(request, obj, form, change=False)

    firm_id = obj.pk
    limits = service.platform_firm_limits(firm_id)
    assert limits["max_members"] == 5 and limits["max_clients"] == 20
    state = service.platform_firm_onboarding(firm_id)
    assert state["owner_invite"] == "pending" and state["owner_invite_email"] == "olive@added.test"

    shown = request.session["owner_link"]
    assert shown["firm"] == str(firm_id) and f"/invite/{firm_id}." in shown["link"]
    with firm_context(firm_id):
        record = Invite.objects.get(firm_id=firm_id)
        assert record.make_owner and record.full_name == "Olive Owner"
        assert shown["link"].rsplit(".", 1)[1] not in record.token_hash  # only a hash is stored, never the secret


def test_a_firm_added_out_of_service_stays_out_of_service(page, request_for):
    form = FirmForm(data={"name": "Dormant Co", "owner_email": "o@dormant.test"}, instance=PlatformFirm())  # is_active left off
    assert form.is_valid(), form.errors
    obj = PlatformFirm()
    page.save_model(request_for(), obj, form, change=False)
    with firm_context(obj.pk):
        from core.models import Firm

        assert Firm.objects.get(pk=obj.pk).is_active is False


def test_saving_an_existing_firm_updates_its_name_and_limits_without_inviting_anyone(page, request_for):
    firm = create_firm("Old Name")
    form = FirmForm(
        data={"name": "New Name", "is_active": "on", "max_members": "3", "suspended_message": "Paused for payment."},
        instance=PlatformFirm(pk=firm.pk, name="Old Name", is_active=True),
    )
    assert form.is_valid(), form.errors
    page.save_model(request_for(), PlatformFirm(pk=firm.pk), form, change=True)
    limits = service.platform_firm_limits(firm.pk)
    assert limits["max_members"] == 3 and limits["suspended_message"] == "Paused for payment."
    assert service.platform_firm_onboarding(firm.pk)["owner_invite"] == "none"


def test_the_change_form_starts_with_the_firms_current_limits():
    firm = create_firm("Has Limits")
    service.platform_set_limits(firm.pk, max_members=4, trial_ends_at=timezone.now() + datetime.timedelta(days=10), suspended_message="Back soon.")
    form = FirmForm(instance=PlatformFirm(pk=firm.pk, name="Has Limits", is_active=True))
    assert form.initial["max_members"] == 4 and form.initial["suspended_message"] == "Back soon."
    assert form.initial["trial_ends_on"] is not None


def test_the_owner_link_button_makes_a_first_invitation_then_replaces_it(page, request_for):
    firm = create_firm("Button Co")
    first = page.owner_link_view(request_for({"owner_email": "o@button.test", "owner_name": "Oona"}), str(firm.pk))
    assert first.status_code == 302
    state = service.platform_firm_onboarding(firm.pk)
    assert state["owner_invite"] == "pending" and state["owner_invite_email"] == "o@button.test"

    request = request_for()
    assert page.owner_link_view(request, str(firm.pk)).status_code == 302
    assert request.session["owner_link"]["firm"] == str(firm.pk)  # a new link, kept for the next view only
    with firm_context(firm.pk):
        assert Invite.objects.filter(firm_id=firm.pk, revoked_at__isnull=True, used_at__isnull=True).count() == 1


def test_the_owner_link_button_says_why_when_it_cannot(page, request_for):
    firm = create_firm("Bad Address Co")
    request = request_for({"owner_email": "not an email"})
    assert page.owner_link_view(request, str(firm.pk)).status_code == 302
    assert "owner_link" not in request.session
    assert any("not an email" in str(m) for m in request._messages)


def test_the_cancel_button_stops_the_invitation(page, request_for):
    firm = create_firm("Cancel Co")
    page.owner_link_view(request_for({"owner_email": "o@cancel.test"}), str(firm.pk))
    assert page.owner_revoke_view(request_for(), str(firm.pk)).status_code == 302
    assert service.platform_firm_onboarding(firm.pk)["owner_invite"] == "revoked"


def test_the_buttons_only_answer_to_a_post_from_someone_who_may_change_firms(page, operator):
    from django.core.exceptions import PermissionDenied

    firm = create_firm("Guarded Co")
    get = RequestFactory().get("/x/")
    get.user = operator
    with pytest.raises(PermissionDenied):
        page.owner_link_view(get, str(firm.pk))
    with pytest.raises(PermissionDenied):
        page.owner_revoke_view(get, str(firm.pk))


def test_the_firm_page_template_compiles_and_the_urls_are_named(page):
    get_template("admin/superadmin/platformfirm/change_form.html")
    names = {u.name for u in page.get_urls()}
    assert {"superadmin_platformfirm_owner_link", "superadmin_platformfirm_owner_revoke"} <= names
