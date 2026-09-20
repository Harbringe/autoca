"""Accounts and the people behind them.

Two sections live here because they are global -- neither belongs to a firm, so
neither needs row-level security or a tenant context:

* **Users** are logins: address, password, whether the account works.
* **Profiles** are people: how their name reads, their designation, their ICAI
  membership number, how to reach them. One per account, created with it by the
  signal in ``core/signals.py``, so the page is never missing.

The platform sections -- firms, memberships, clients, audit logs, jobs -- read
across firms, which only the gated views in ``superadmin/sql.py`` can do, so they
are registered in ``superadmin/admin.py``. That module also re-registers
Profiles with the controls for putting a person in a firm, because those read
the same views. Without the add-on, this file still gives a working admin for
accounts and profiles.

A firm's own work -- clients' statements, ledgers, classifications, journals --
is not in this admin at all. It is done in the app, behind a review queue, an
approval step and an append-only journal.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.db import models as db_models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from core.models import Profile, User

# ``django.contrib.auth`` registers Group on whatever the default site is, and
# this app does not use it: permissions come from a person's role in a firm
# (core/rbac.py) and their client assignments, not from Django groups. Leaving
# the page up would offer a way to grant access that nothing reads.
admin.site.unregister(Group)


# ---------------------------------------------------------------------------
# Users: the login
# ---------------------------------------------------------------------------


class PlatformUserCreationForm(UserCreationForm):
    """Two password boxes that hash what you type, not one that stores it raw.

    A plain ``ModelAdmin`` over a user model renders ``password`` as an ordinary
    text field, and whatever is typed is written to the column as if it were
    already a hash. The account then cannot be signed into and nothing says so.
    This is Django's own form, pointed at our user model.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "full_name")


class PlatformUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """The login, and only the login. The person is under Profiles.

    ``groups`` and ``user_permissions`` come from ``PermissionsMixin`` and nothing
    in this app reads them, so they are not shown.
    """

    add_form = PlatformUserCreationForm
    form = PlatformUserChangeForm
    model = User

    list_display = ("email", "full_name", "is_active", "is_superuser", "last_login", "profile_link")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    readonly_fields = ("last_login", "last_login_ip", "profile_link")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Person", {"fields": ("full_name", "profile_link")}),
        (
            "Platform access",
            {
                "fields": ("is_active", "is_staff", "is_superuser"),
                "description": (
                    "Staff and superuser are Django admin powers, not powers inside a "
                    "firm. A superuser who belongs to no firm is the platform owner. "
                    "What someone may do inside a firm is set on their profile."
                ),
            },
        ),
        ("Security", {"fields": ("last_login", "last_login_ip")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "password1", "password2"),
                "description": "A profile is created with the account. Put them in a firm there.",
            },
        ),
    )

    def has_delete_permission(self, request, obj=None):
        """Accounts are deactivated, never deleted.

        A person's name is attached to work: who approved a voucher, who placed a
        transaction, who did what in the audit log. Deleting the account would
        quietly rewrite that record. Clearing ``is active`` stops them signing in
        and leaves it intact.
        """
        return False

    @admin.display(description="Profile")
    def profile_link(self, obj):
        profile = getattr(obj, "profile", None) if obj and obj.pk else None
        if profile is None:
            return "—"
        return format_html(
            '<a href="{}">{}</a>', reverse("admin:core_profile_change", args=[profile.pk]), "Open profile"
        )


# ---------------------------------------------------------------------------
# Profiles: the person
# ---------------------------------------------------------------------------


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Who a person is. ``superadmin.admin`` extends this with their place in a firm."""

    #: Django 6 flips URL fields from http to https by default, and until then
    #: leaving it unstated warns on every render.
    formfield_overrides = {
        db_models.URLField: {"form_class": forms.URLField, "assume_scheme": "https"}
    }

    list_display = ("name", "email", "designation", "icai_membership_no", "phone")
    list_filter = ("designation",)
    search_fields = ("display_name", "user__email", "user__full_name", "icai_membership_no")
    readonly_fields = ("account", "created_at")

    fieldsets = (
        ("Who they are", {"fields": ("account", "display_name", "designation", "icai_membership_no")}),
        ("How to reach them", {"fields": ("phone", "avatar_url", "timezone")}),
        ("Internal", {"fields": ("notes", "created_at")}),
    )

    def has_add_permission(self, request):
        # A profile is made with its account. Adding one here would mean an
        # account with two, or a profile with none.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Name", ordering="user__email")
    def name(self, obj):
        return obj.name

    @admin.display(description="Email", ordering="user__email")
    def email(self, obj):
        return obj.user.email

    @admin.display(description="Account")
    def account(self, obj):
        if obj is None or not obj.pk:
            return "—"
        user = obj.user
        state = "active" if user.is_active else "deactivated"
        last = (
            timezone.localtime(user.last_login).strftime("%d %b %Y, %H:%M")
            if user.last_login
            else "never signed in"
        )
        mfa = "two-factor on" if user.has_mfa else "two-factor off"
        return format_html(
            '<a href="{}">{}</a> <span style="opacity:.6">&mdash; {}, {}, {}</span>',
            reverse("admin:core_user_change", args=[user.pk]),
            user.email,
            state,
            last,
            mfa,
        )
