"""The platform layer: who may open the admin, what it can read, and what it writes.

Three groups of tests, in the order the guarantees depend on each other.

* **The door.** Only the platform owner -- a superuser who belongs to no firm --
  opens the admin, and the old console API is gone.
* **The views.** The owner reads every firm through them; anyone else reads
  nothing; nobody writes through them; and none of them carries a firm's books.
* **The admin.** Every section opens without choosing a firm, clients are
  visible and never editable, and a person's place in a firm is set from their
  profile while the firm's own rules still hold.
"""

from __future__ import annotations

import contextlib
import datetime

import pytest
from django.db import DatabaseError, connection, transaction

from api.tests.conftest import member, sign_in
from core.db.session import _apply_user, firm_context
from core.models import ClientAssignment, FirmMembership, Profile, Role, User
from core.provisioning import create_client, create_firm
from superadmin import sql
from superadmin.models import PlatformClient, PlatformFirm, PlatformMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def firm_a():
    return create_firm("Alpha & Co")


@pytest.fixture
def firm_b():
    return create_firm("Beta Associates")


@pytest.fixture
def operator():
    """The platform owner: a superuser with no firm membership at all."""
    return User.objects.create_user(
        email="operator@example.test", password="x" * 20, is_superuser=True, is_staff=True
    )


@pytest.fixture
def views():
    with connection.cursor() as cursor:
        if not sql.views_installed(cursor):
            pytest.skip("autoca_platform_reader is not set up on this Postgres cluster")


@contextlib.contextmanager
def reading_as(user):
    """A transaction whose user context is ``user``, the way a request's is."""
    with transaction.atomic():
        _apply_user(str(user.pk) if user else "")
        yield
        transaction.set_rollback(True)


# ---------------------------------------------------------------------------
# The door
# ---------------------------------------------------------------------------


def _admin_reachable(http) -> bool:
    """Django bounces a signed-in user it will not admit back to its own login.

    It answers 200 either way, so the status code says nothing. The redirect to
    ``/admin/login/`` is the refusal.
    """
    response = http.get("/admin/", follow=True)
    final = response.redirect_chain[-1][0] if response.redirect_chain else "/admin/"
    return "/admin/login/" not in final


def test_the_admin_belongs_to_the_platform_owner(operator):
    assert _admin_reachable(sign_in(operator))


@pytest.mark.parametrize("role", list(Role))
def test_a_firms_own_staff_never_reach_the_admin(firm_a, role):
    """Not even with both Django flags set: firm membership decides, not a flag."""
    user = member(firm_a, role, f"{role.lower()}-admin@a.test").user
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])
    assert not _admin_reachable(sign_in(user))


def test_the_platform_owner_gets_a_session_but_no_firm_data(operator):
    http = sign_in(operator)
    me = http.get("/api/v1/me/")
    assert me.status_code == 200
    assert me.json()["firm"] is None
    assert http.get("/api/v1/clients/").status_code == 403


def test_a_firmless_ordinary_user_is_refused():
    user = User.objects.create_user(email="nobody@example.test", password="x" * 20)
    assert sign_in(user).get("/api/v1/me/").status_code == 403


def test_the_console_api_is_gone(operator):
    """The admin is the one panel. The console's endpoints must not linger.

    The tenancy middleware refuses the path before routing, so the response is
    a 403 either way; the route table is what proves nothing is behind it.
    """
    from django.urls import Resolver404, resolve

    with pytest.raises(Resolver404):
        resolve("/api/superadmin/firms/")
    assert sign_in(operator).get("/api/superadmin/firms/").status_code in {403, 404}


# ---------------------------------------------------------------------------
# The views
# ---------------------------------------------------------------------------


def test_the_owner_reads_every_firm(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    member(firm_b, Role.STAFF, "staff@b.test")
    with firm_context(firm_b.pk):
        create_client(firm_b, "Beta Client", datetime.date(2026, 4, 1))

    with reading_as(operator):
        assert {"Alpha & Co", "Beta Associates"} <= set(PlatformFirm.objects.values_list("name", flat=True))
        assert {"admin@a.test", "staff@b.test"} <= set(PlatformMembership.objects.values_list("email", flat=True))
        assert list(PlatformClient.objects.values_list("firm_name", "name")) == [("Beta Associates", "Beta Client")]


def test_everyone_else_reads_nothing(views, firm_a, firm_b):
    """A firm's own administrator, and a request with no user at all."""
    admin = member(firm_a, Role.FIRM_ADMIN, "admin@a.test").user
    member(firm_b, Role.STAFF, "staff@b.test")

    for who in (admin, None):
        with reading_as(who):
            assert PlatformFirm.objects.count() == 0
            assert PlatformMembership.objects.count() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.platform_firms SET is_active = false",
        "DELETE FROM app.platform_memberships",
        "INSERT INTO app.platform_firms (id, name, is_active, created_at) VALUES (gen_random_uuid(), 'x', true, now())",
        "UPDATE app.platform_clients SET fy_start = now()::date",
    ],
)
def test_nobody_writes_through_the_views(views, operator, firm_a, statement):
    """Views run as a BYPASSRLS owner, so a write through one would cross firms."""
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    with pytest.raises(DatabaseError), reading_as(operator):
        with connection.cursor() as cursor:
            cursor.execute(statement)


def test_no_view_carries_a_firms_books(views):
    """Directory columns only. Counts of accounts and statements, never their contents."""
    forbidden = ("narration", "amount", "paise", "balance", "account_number", "gstin", "ledger", "result", "holder")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'app' AND table_name LIKE 'platform_%%'"
        )
        columns = cursor.fetchall()
    assert columns, "the views should exist"
    leaks = [(t, c) for t, c in columns if any(word in c for word in forbidden)]
    assert not leaks, f"these columns expose a firm's books: {leaks}"


def test_the_read_models_refuse_to_save(views, operator, firm_a):
    with reading_as(operator):
        firm = PlatformFirm.objects.get(pk=firm_a.pk)
        with pytest.raises(TypeError):
            firm.save()
        with pytest.raises(TypeError):
            firm.delete()


def test_the_directory_functions_refuse_a_non_owner_in_the_database(views, firm_a):
    user = member(firm_a, Role.FIRM_ADMIN, "admin@a.test").user
    with pytest.raises(DatabaseError), transaction.atomic():
        _apply_user(str(user.pk))
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM app.superadmin_firms()")


# ---------------------------------------------------------------------------
# The admin
# ---------------------------------------------------------------------------


def test_the_admin_registers_the_platform_and_not_the_books():
    from django.contrib import admin
    from django.contrib.auth.models import Group

    from banking.models import BankAccount, Statement, StatementTransaction
    from classify.models import ClassificationRule, LedgerAccount, Party, TransactionClassification
    from core.models import AuditLog, Client, Firm, Job
    from documents.models import Document
    from ledger.models import JournalEntry, JournalLine, VoucherSequence
    from superadmin.models import PlatformAuditLog, PlatformJob

    registered = set(admin.site._registry)
    for model in (User, Profile, PlatformFirm, PlatformMembership, PlatformClient, PlatformAuditLog, PlatformJob):
        assert model in registered, f"{model.__name__} should be in the admin"
    for model in (
        # Firm-scoped tables are reached through the views, not directly.
        Firm, FirmMembership, Client, ClientAssignment, AuditLog, Job,
        # A firm's books are not the platform's business.
        BankAccount, Statement, StatementTransaction, LedgerAccount, Party,
        ClassificationRule, TransactionClassification, JournalEntry, JournalLine,
        VoucherSequence, Document, Group,
    ):
        assert model not in registered, f"{model.__name__} should not be in the admin"


@pytest.mark.parametrize(
    "path",
    [
        "/admin/",
        "/admin/core/user/",
        "/admin/core/profile/",
        "/admin/superadmin/platformfirm/",
        "/admin/superadmin/platformmembership/",
        "/admin/superadmin/platformclient/",
        "/admin/superadmin/platformauditlog/",
        "/admin/superadmin/platformjob/",
    ],
)
def test_every_section_opens_without_choosing_a_firm(views, operator, firm_a, path):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    assert sign_in(operator).get(path).status_code == 200


def test_the_firms_page_lists_every_firm(views, operator, firm_a, firm_b):
    body = sign_in(operator).get("/admin/superadmin/platformfirm/").content.decode()
    assert "Alpha &amp; Co" in body
    assert "Beta Associates" in body


def test_a_firm_is_created_and_renamed_from_the_admin(views, operator):
    http = sign_in(operator)
    created = http.post(
        "/admin/superadmin/platformfirm/add/", {"name": "Made In Admin", "is_active": "on", "_save": "Save"}
    )
    assert created.status_code == 302, created.content[:500]

    with reading_as(operator):
        firm = PlatformFirm.objects.get(name="Made In Admin")

    renamed = http.post(
        f"/admin/superadmin/platformfirm/{firm.pk}/change/",
        {
            "name": "Renamed In Admin",
            "is_active": "on",
            # The read-only inlines still render management forms in a browser.
            "memberships-TOTAL_FORMS": "0", "memberships-INITIAL_FORMS": "0",
            "clients-TOTAL_FORMS": "0", "clients-INITIAL_FORMS": "0",
            "_save": "Save",
        },
    )
    assert renamed.status_code == 302, renamed.content[:800]
    with reading_as(operator):
        assert PlatformFirm.objects.get(pk=firm.pk).name == "Renamed In Admin"


def test_clients_are_visible_and_never_editable(views, operator, firm_a):
    from django.contrib import admin

    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    with firm_context(firm_a.pk):
        client = create_client(firm_a, "Vasant Traders", datetime.date(2026, 4, 1))

    http = sign_in(operator)
    listing = http.get("/admin/superadmin/platformclient/").content.decode()
    assert "Vasant Traders" in listing
    assert http.get("/admin/superadmin/platformclient/add/").status_code == 403

    page = admin.site._registry[PlatformClient]
    assert not page.has_add_permission(None)
    assert not page.has_change_permission(None)
    assert not page.has_delete_permission(None)
    assert http.get(f"/admin/superadmin/platformclient/{client.pk}/change/").status_code == 200


def test_the_business_description_shows_in_the_client_admin(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    with firm_context(firm_a.pk):
        client = create_client(firm_a, "Vasant Traders", datetime.date(2026, 4, 1))
        client.business_profile = "Wholesale cloth trader with a rented godown"
        client.save(update_fields=["business_profile"])

    http = sign_in(operator)
    page = http.get(f"/admin/superadmin/platformclient/{client.pk}/change/").content.decode()
    assert "Wholesale cloth trader" in page
    found = http.get("/admin/superadmin/platformclient/?q=godown").content.decode()
    assert "Vasant Traders" in found


def test_an_account_made_in_the_admin_can_sign_in():
    """The add form must hash the password, not store what was typed."""
    from django.contrib import admin

    form_class = admin.site._registry[User].add_form
    form = form_class(data={
        "email": "made-in-admin@example.test",
        "full_name": "Made In Admin",
        "password1": "a-long-enough-passphrase-9214",
        "password2": "a-long-enough-passphrase-9214",
    })
    assert form.is_valid(), form.errors
    created = form.save()
    assert created.check_password("a-long-enough-passphrase-9214")
    assert created.password != "a-long-enough-passphrase-9214"
    assert hasattr(created, "profile"), "every account gets a profile"


def test_accounts_and_profiles_are_never_deleted_or_added_by_hand():
    from django.contrib import admin

    assert not admin.site._registry[User].has_delete_permission(None)
    assert not admin.site._registry[Profile].has_delete_permission(None)
    assert not admin.site._registry[Profile].has_add_permission(None)


# ---------------------------------------------------------------------------
# A person's place in a firm, set from their profile
# ---------------------------------------------------------------------------


def _save_profile(http, user, **place):
    """Post the profile form the way the page does, with the firm fields given."""
    profile = Profile.objects.get(user=user)
    data = {
        "display_name": profile.display_name,
        "designation": profile.designation,
        "icai_membership_no": profile.icai_membership_no,
        "phone": profile.phone,
        "avatar_url": profile.avatar_url,
        "timezone": profile.timezone,
        "notes": profile.notes,
        "firm": "",
        "role": Role.STAFF,
        "manager": "",
        "membership_active": "on",
        "_save": "Save",
    }
    for key, value in place.items():
        if value is True:
            data[key] = "on"
        elif value is False:
            data.pop(key, None)
        else:
            data[key] = str(value)
    return http.post(f"/admin/core/profile/{profile.pk}/change/", data)


def _place_of(operator, user):
    with reading_as(operator):
        return PlatformMembership.objects.filter(user_id=user.pk).first()


def test_the_profile_puts_a_person_in_a_firm(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    person = User.objects.create_user(email="new@example.test", password="x" * 20)

    response = _save_profile(sign_in(operator), person, firm=firm_a.pk, role=Role.SENIOR_CA)
    assert response.status_code == 302, response.content[:800]

    place = _place_of(operator, person)
    assert place.firm_id == firm_a.pk
    assert place.role == Role.SENIOR_CA


def test_the_profile_moves_a_person_between_firms_in_one_step(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    member(firm_b, Role.FIRM_ADMIN, "admin@b.test")
    person = member(firm_a, Role.STAFF, "mover@example.test").user

    response = _save_profile(sign_in(operator), person, firm=firm_b.pk, role=Role.STAFF)
    assert response.status_code == 302, response.content[:800]

    assert _place_of(operator, person).firm_id == firm_b.pk


def test_the_profile_sets_who_someone_reports_to(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    senior = member(firm_a, Role.SENIOR_CA, "senior@a.test")
    junior = member(firm_a, Role.STAFF, "junior@a.test").user

    response = _save_profile(sign_in(operator), junior, firm=firm_a.pk, role=Role.STAFF, manager=senior.pk)
    assert response.status_code == 302, response.content[:800]
    assert _place_of(operator, junior).manager_id == senior.pk


def test_the_profile_refuses_a_manager_from_another_firm(views, operator, firm_a, firm_b):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    other_senior = member(firm_b, Role.SENIOR_CA, "senior@b.test")
    junior = member(firm_a, Role.STAFF, "junior@a.test").user

    response = _save_profile(sign_in(operator), junior, firm=firm_a.pk, role=Role.STAFF, manager=other_senior.pk)
    assert response.status_code == 200
    assert b"same firm" in response.content
    assert _place_of(operator, junior).manager_id is None


def test_the_profile_keeps_the_firm_with_an_administrator(views, operator, firm_a):
    """Taking out the last administrator is refused, as a message on the form."""
    only_admin = member(firm_a, Role.FIRM_ADMIN, "admin@a.test").user

    response = _save_profile(sign_in(operator), only_admin, firm="")
    assert response.status_code == 200
    assert b"at least one active firm administrator" in response.content
    assert _place_of(operator, only_admin) is not None


def test_the_profile_refuses_to_strand_a_leads_team(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    senior = member(firm_a, Role.SENIOR_CA, "senior@a.test")
    junior = member(firm_a, Role.STAFF, "junior@a.test")
    with firm_context(firm_a.pk):
        junior.manager = senior
        junior.save(update_fields=["manager"])

    response = _save_profile(sign_in(operator), senior.user, firm="")
    assert response.status_code == 200
    assert b"still leads" in response.content


def test_the_profile_shows_the_clients_they_work_on_without_editing_them(views, operator, firm_a):
    member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    junior = member(firm_a, Role.STAFF, "junior@a.test")
    with firm_context(firm_a.pk):
        junior.scope_all_clients = False
        junior.save(update_fields=["scope_all_clients"])
        client = create_client(firm_a, "Vasant Traders", datetime.date(2026, 4, 1))
        ClientAssignment.objects.create(firm_id=firm_a.pk, client=client, membership=junior)

    profile = Profile.objects.get(user=junior.user)
    body = sign_in(operator).get(f"/admin/core/profile/{profile.pk}/change/").content.decode()
    assert "Vasant Traders" in body
    assert 'name="clients_worked_on"' not in body, "clients are shown, not a field to edit"


def test_the_memberships_list_opens_the_persons_profile(views, operator, firm_a):
    person = member(firm_a, Role.FIRM_ADMIN, "admin@a.test")
    profile = Profile.objects.get(user=person.user)

    response = sign_in(operator).get(f"/admin/superadmin/platformmembership/{person.pk}/change/")
    assert response.status_code == 302
    assert response["Location"] == f"/admin/core/profile/{profile.pk}/change/"
