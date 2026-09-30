"""The platform sections of the admin: firms, who works where, clients, the trail.

Two rules shape every class here.

**Reads go across firms, through the gated views.** Every list is a ``Platform*``
model over a view in ``superadmin/sql.py``, so the Firms page lists every firm,
Clients lists every firm's clients, and nothing has to be "chosen" first. The
views return rows only to the platform owner, in the database.

**Writes go into one firm, through the service.** Nothing here saves a
``Platform*`` row -- they raise if asked. Creating or renaming a firm, and
putting a person in a firm or changing their place in it, call the functions at
the end of ``teams/service.py``. Each opens the context of the one firm it
changes and keeps that firm's own rules: an active administrator always, a team
leader from the same firm, nobody left leading people or clients with nowhere to
go.

Clients are shown, never edited, and the data behind them -- statements,
ledgers, classifications, journals -- is not here at all. That is the firm's
work, done in the app.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

import core.admin  # noqa: F401  registers Profile first, so it can be replaced below
from core.admin import ProfileAdmin
from core.models import Profile, Role
from superadmin.models import (
    PlatformAuditLog,
    PlatformClient,
    PlatformClientAssignment,
    PlatformFirm,
    PlatformJob,
    PlatformMembership,
)
from teams import service
from teams.service import TEAM_ROLES, TeamError


class ReadOnlyAdmin(admin.ModelAdmin):
    """A list you can open and read, with no Add, Save or Delete."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Refusing change while allowing view makes Django render the detail
        # page read-only rather than hiding it.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _profile_url(user_id) -> str | None:
    profile = Profile.objects.filter(user_id=user_id).only("pk").first()
    return reverse("admin:core_profile_change", args=[profile.pk]) if profile else None


# ---------------------------------------------------------------------------
# Firms
# ---------------------------------------------------------------------------


class FirmMembersInline(ReadOnlyInline):
    model = PlatformMembership
    fk_name = "firm"
    verbose_name = "person"
    verbose_name_plural = "People"
    fields = ("person", "role", "manager_email", "scope_all_clients", "is_owner", "is_active")
    readonly_fields = fields

    @admin.display(description="Person")
    def person(self, obj):
        url = _profile_url(obj.user_id)
        name = obj.full_name or obj.email
        return format_html('<a href="{}">{}</a>', url, name) if url else name


class FirmClientsInline(ReadOnlyInline):
    model = PlatformClient
    fk_name = "firm"
    verbose_name_plural = "Clients"
    fields = ("client", "fy_start", "lead_email", "team_size", "bank_account_count", "statement_count")
    readonly_fields = fields

    @admin.display(description="Client")
    def client(self, obj):
        return format_html(
            '<a href="{}">{}</a>', reverse("admin:superadmin_platformclient_change", args=[obj.pk]), obj.name
        )


class FirmForm(forms.ModelForm):
    class Meta:
        model = PlatformFirm
        fields = ("name", "is_active")

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if len(name) < 2:
            raise forms.ValidationError("Give the firm a name.")
        return name


@admin.register(PlatformFirm)
class PlatformFirmAdmin(admin.ModelAdmin):
    """Every firm on the platform. Create one, rename it, take it out of service.

    Creating is the case that looks impossible under row-level security and is
    not: ``create_firm`` mints the id, opens a context for it, and inserts the
    row into its own context. Deleting is not offered; a firm owns clients,
    books and an audit trail, and ``is active`` is what "we stopped" means.
    """

    form = FirmForm
    list_display = ("name", "is_active", "member_count", "client_count", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("member_count", "client_count", "created_at")
    inlines = (FirmMembersInline, FirmClientsInline)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("name", "is_active")
        return ("name", "is_active", "member_count", "client_count", "created_at")

    def get_inlines(self, request, obj):
        return self.inlines if obj is not None else ()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        name, is_active = form.cleaned_data["name"], form.cleaned_data["is_active"]
        if change:
            service.platform_update_firm(obj.pk, name=name, is_active=is_active)
            return
        from core.provisioning import create_firm

        created = create_firm(name)
        if not is_active:
            service.platform_update_firm(created.pk, name=name, is_active=False)
        # The admin redirects to the new row's page and logs the addition by
        # primary key, so it needs to know which firm was made.
        obj.pk = created.pk


# ---------------------------------------------------------------------------
# Who works where
# ---------------------------------------------------------------------------


@admin.register(PlatformMembership)
class PlatformMembershipAdmin(ReadOnlyAdmin):
    """Every person's place in every firm, in one list.

    Read-only on purpose. A membership is changed on the person's profile, where
    the rest of what is true about them sits, so there is one place to do it.
    Opening a row goes there.
    """

    list_display = ("email", "full_name", "firm_name", "role", "manager_email", "scope_all_clients", "is_owner", "is_active")
    list_filter = ("firm", "role", "is_active", "is_owner")
    search_fields = ("email", "full_name", "firm_name")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        membership = PlatformMembership.objects.filter(pk=object_id).first()
        url = _profile_url(membership.user_id) if membership else None
        if url is None:
            return super().change_view(request, object_id, form_url, extra_context)
        return HttpResponseRedirect(url)


# ---------------------------------------------------------------------------
# Clients: seen, never edited
# ---------------------------------------------------------------------------


class ClientTeamInline(ReadOnlyInline):
    model = PlatformClientAssignment
    fk_name = "client"
    verbose_name = "assigned person"
    verbose_name_plural = "Assigned"
    fields = ("person", "created_at")
    readonly_fields = fields

    @admin.display(description="Person")
    def person(self, obj):
        url = _profile_url(obj.user_id)
        return format_html('<a href="{}">{}</a>', url, obj.email) if url else obj.email


@admin.register(PlatformClient)
class PlatformClientAdmin(ReadOnlyAdmin):
    """Which clients each firm carries, who leads them, and how busy they are.

    The counts say how many bank accounts and statements a client has without
    opening any of them. What is in those statements is the firm's business.
    The description of what the client does is shown too, so a support question
    ("why is this client's sales ledger empty?") starts from what they trade in.
    """

    list_display = ("name", "firm_name", "fy_start", "lead_email", "team_size", "bank_account_count", "statement_count")
    list_filter = ("firm",)
    search_fields = ("name", "firm_name", "business_profile")
    fields = ("name", "firm_name", "fy_start", "business_profile", "lead_email", "team_size", "bank_account_count", "statement_count", "created_at")
    readonly_fields = fields
    inlines = (ClientTeamInline,)


# ---------------------------------------------------------------------------
# What happened
# ---------------------------------------------------------------------------


@admin.register(PlatformAuditLog)
class PlatformAuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "firm_name", "user_email", "method", "path", "status_code", "duration_ms")
    list_filter = ("firm", "method", "status_code")
    search_fields = ("path", "user_email", "request_id")
    date_hierarchy = "created_at"


@admin.register(PlatformJob)
class PlatformJobAdmin(ReadOnlyAdmin):
    """Background work. The page to open when a firm says an upload never finished."""

    list_display = ("created_at", "firm_name", "kind", "status", "progress", "message", "created_by_email")
    list_filter = ("firm", "status", "kind")
    search_fields = ("message", "created_by_email", "error_code")
    date_hierarchy = "created_at"


# ---------------------------------------------------------------------------
# Profiles, with the person's place in a firm
# ---------------------------------------------------------------------------


class _DryRun(Exception):
    """Raised to roll back a rehearsal of a membership change."""


def apply_place(user, current: PlatformMembership | None, data: dict) -> None:
    """Make the person's place in a firm match what the profile form says.

    Works out whether this is joining a firm, leaving one, moving between two,
    or a change inside the same firm, and calls the service for each step. A
    move is a removal from one firm's context and a join in another's, inside
    the caller's transaction, so it happens entirely or not at all.
    """
    firm = data.get("firm")
    role = data.get("role") or Role.STAFF
    manager = data.get("manager") if not data.get("make_owner") else None
    values = dict(
        role=role,
        manager_id=manager.pk if manager else None,
        scope_all_clients=bool(data.get("scope_all_clients")),
        is_active=bool(data.get("membership_active")),
        make_owner=bool(data.get("make_owner")),
    )

    if firm is None:
        if current is not None:
            service.platform_remove(current.pk, current.firm_id)
        return

    if current is not None and current.firm_id == firm.pk:
        service.platform_update(current.pk, firm.pk, **values)
        return

    if current is not None:
        service.platform_remove(current.pk, current.firm_id)
    joined = service.platform_assign(
        user,
        firm.pk,
        role=role,
        manager_id=values["manager_id"],
        scope_all_clients=values["scope_all_clients"],
    )
    service.platform_update(joined.pk, firm.pk, **values)


class ProfileWithFirmForm(forms.ModelForm):
    """The profile's own fields, plus the person's place in a firm.

    The firm fields are not columns on ``Profile``; they describe a membership,
    which lives in a firm and is written through the service. They are checked
    here by rehearsing the change and rolling it back, so a broken firm rule
    comes back as a message on the form rather than a server error after Save.
    """

    #: Declared rather than generated: a ModelForm builds its fields when the
    #: class is defined, before the admin's ``formfield_overrides`` apply, and a
    #: URL field without a stated scheme warns until Django 6.
    avatar_url = forms.URLField(required=False, assume_scheme="https", label="Avatar URL")

    firm = forms.ModelChoiceField(
        queryset=PlatformFirm.objects.all(),
        required=False,
        help_text="Leave empty to take them out of their firm. An account belongs to one firm.",
    )
    role = forms.ChoiceField(choices=Role.choices, initial=Role.STAFF)
    manager = forms.ModelChoiceField(
        queryset=PlatformMembership.objects.filter(role__in=[Role.SENIOR_CA, Role.FIRM_ADMIN], is_active=True),
        required=False,
        label="Reports to",
        help_text="Choose the direct manager: administrators report to the owner, Senior CAs to an administrator, and Staff/Read-only to a Senior CA.",
    )
    scope_all_clients = forms.BooleanField(required=False, label="Sees every client in the firm")
    membership_active = forms.BooleanField(
        required=False, initial=True, label="Active in the firm",
        help_text="Off keeps them in the firm but stops them working in it.",
    )
    make_owner = forms.BooleanField(
        required=False, label="Firm owner",
        help_text="Makes them the owner. Only an active administrator can be. Ownership is moved, never removed.",
    )

    class Meta:
        model = Profile
        fields = ("display_name", "designation", "icai_membership_no", "phone", "avatar_url", "timezone", "notes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current = None
        if self.instance and self.instance.pk:
            self.current = PlatformMembership.objects.filter(user_id=self.instance.user_id).first()
        if self.current is not None and not self.is_bound:
            self.initial.update(
                firm=self.current.firm_id,
                role=self.current.role,
                manager=self.current.manager_id,
                scope_all_clients=self.current.scope_all_clients,
                membership_active=self.current.is_active,
                make_owner=self.current.is_owner,
            )
        self.fields["manager"].label_from_instance = lambda m: f"{m.email} ({m.get_role_display()}, {m.firm_name})"

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        firm, manager, role = data.get("firm"), data.get("manager"), data.get("role")
        if firm is not None and manager is not None and role in TEAM_ROLES and manager.firm_id != firm.pk:
            self.add_error("manager", "Pick someone from the same firm.")
            return data
        if manager is not None and role not in TEAM_ROLES:
            self.add_error("manager", "Only Staff and Read-only members report to someone.")
            return data
        if self.current is not None and self.current.is_owner and not data.get("make_owner") and firm is not None and firm.pk == self.current.firm_id:
            self.add_error("make_owner", "Ownership is moved, not removed. Make someone else the owner.")
            return data
        try:
            with transaction.atomic():
                apply_place(self.instance.user, self.current, data)
                raise _DryRun
        except _DryRun:
            pass
        except TeamError as exc:
            raise forms.ValidationError(exc.messages) from exc
        return data


admin.site.unregister(Profile)


@admin.register(Profile)
class PlatformProfileAdmin(ProfileAdmin):
    """Everything about a person, and where they work.

    Put them in a firm, move them to another, take them out, set their role,
    who they report to, whether they see every client, whether they own the
    firm. The clients they work on are shown, not edited: that is the firm's
    own decision, made in the app.
    """

    form = ProfileWithFirmForm
    list_display = ("name", "email", "firm_name", "role", "designation", "icai_membership_no")
    list_filter = ("designation",)

    fieldsets = (
        ("Who they are", {"fields": ("account", "display_name", "designation", "icai_membership_no")}),
        (
            "Where they work",
            {
                "fields": ("firm", "role", "manager", "scope_all_clients", "membership_active", "make_owner"),
                "description": (
                    "A person belongs to at most one firm. Changing the firm moves them: "
                    "they leave the old one and join the new one together. The firm's own "
                    "rules still apply, so the last administrator can't be removed and "
                    "nobody who still leads people or clients can step down."
                ),
            },
        ),
        ("Their work", {"fields": ("clients_worked_on", "recent_changes")}),
        ("How to reach them", {"fields": ("phone", "avatar_url", "timezone")}),
        ("Internal", {"fields": ("notes", "created_at")}),
    )
    readonly_fields = ("account", "created_at", "clients_worked_on", "recent_changes")

    def get_queryset(self, request):
        place = PlatformMembership.objects.filter(user_id=OuterRef("user_id"))
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .annotate(
                firm_name=Subquery(place.values("firm_name")[:1]),
                role=Subquery(place.values("role")[:1]),
            )
        )

    @admin.display(description="Firm", ordering="firm_name")
    def firm_name(self, obj):
        return obj.firm_name or "—"

    @admin.display(description="Role", ordering="role")
    def role(self, obj):
        return Role(obj.role).label if obj.role else "—"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        apply_place(obj.user, form.current, form.cleaned_data)

    @admin.display(description="Clients they work on")
    def clients_worked_on(self, obj):
        if obj is None or not obj.pk:
            return "—"
        membership = PlatformMembership.objects.filter(user_id=obj.user_id).first()
        if membership is None:
            return format_html("<em>{}</em>", "Not in a firm.")
        if membership.role == Role.FIRM_ADMIN or membership.scope_all_clients:
            return format_html("<em>{}</em>", f"Every client of {membership.firm_name}.")
        rows = [(c.name, "leads") for c in PlatformClient.objects.filter(lead_id=membership.pk).order_by("name")]
        rows += [
            (a.client_name, "assigned")
            for a in PlatformClientAssignment.objects.filter(membership_id=membership.pk).order_by("client_name")
        ]
        if not rows:
            return format_html("<em>{}</em>", "No clients yet. They can see nothing until the firm assigns some.")
        return format_html_join("", '<div>{} <span style="opacity:.6">&mdash; {}</span></div>', rows)

    @admin.display(description="Recent changes to their place")
    def recent_changes(self, obj):
        if obj is None or not obj.pk:
            return "—"
        membership = PlatformMembership.objects.filter(user_id=obj.user_id).first()
        if membership is None:
            return "—"
        from core.db.session import firm_context
        from teams.models import TeamEvent

        # Team events belong to the firm, so they are read inside its context,
        # and read in full before the context closes.
        with firm_context(membership.firm_id):
            events = list(TeamEvent.objects.filter(member_id=membership.pk).order_by("-created_at")[:10])
        if not events:
            return format_html("<em>{}</em>", "Nothing recorded yet.")
        return format_html_join(
            "",
            '<div>{} <span style="opacity:.6">&mdash; {}, {}</span></div>',
            [
                (
                    e.get_kind_display(),
                    e.detail.get("actor", "someone"),
                    # In the site's time zone, like every other date on the page.
                    timezone.localtime(e.created_at).strftime("%d %b %Y, %H:%M"),
                )
                for e in events
            ],
        )
