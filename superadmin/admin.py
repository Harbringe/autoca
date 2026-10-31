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

import datetime
import logging

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
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
    PlatformFirmStats,
    PlatformInvite,
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
    """The firm's name and whether it is in service, plus what is agreed with it.

    Adding a firm is one step: its name, the person who will own it (who is sent an invitation, never a password), and any limits.
    The limits are not columns of the firm's directory view, so they are read and written through the service, in the firm's own
    context.
    """

    owner_name = forms.CharField(label="Owner's name", required=False, max_length=255)
    owner_email = forms.EmailField(
        label="Owner's email",
        required=False,
        help_text="They are sent an invitation to set their own password and authenticator. Nobody else ever sees either.",
    )
    max_members = forms.IntegerField(label="Limit on people", required=False, min_value=1, help_text="Active people and invitations waiting. Empty means no limit.")
    max_clients = forms.IntegerField(label="Limit on clients", required=False, min_value=1, help_text="Empty means no limit.")
    trial_ends_on = forms.DateField(label="Trial ends on", required=False, widget=forms.DateInput(attrs={"type": "date"}), help_text="Shows a banner to the firm's administrators in the last 14 days. Nothing switches off by itself.")
    suspended_message = forms.CharField(
        label="Message when out of service",
        required=False,
        max_length=500,
        help_text="Shown to the firm's people if they try to sign in while the firm is switched off.",
    )

    class Meta:
        model = PlatformFirm
        fields = ("name", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            try:
                limits = service.platform_firm_limits(self.instance.pk)
            except TeamError:
                limits = {}
            self.initial.setdefault("max_members", limits.get("max_members"))
            self.initial.setdefault("max_clients", limits.get("max_clients"))
            ends = limits.get("trial_ends_at")
            self.initial.setdefault("trial_ends_on", ends.date() if ends else None)
            self.initial.setdefault("suspended_message", limits.get("suspended_message", ""))
        else:
            self.fields["owner_email"].required = True
            self.initial.setdefault("is_active", True)
            del self.fields["suspended_message"]

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if len(name) < 2:
            raise forms.ValidationError("Give the firm a name.")
        return name

    def trial_end(self):
        """The end of the trial day as a moment in time, or None."""
        day = self.cleaned_data.get("trial_ends_on")
        if day is None:
            return None
        return timezone.make_aware(datetime.datetime.combine(day, datetime.time(23, 59, 59)))


@admin.register(PlatformFirm)
class PlatformFirmAdmin(admin.ModelAdmin):
    """Every firm on the platform. Create one, rename it, take it out of service, and see how far its onboarding has got.

    Creating is the case that looks impossible under row-level security and is
    not: ``create_firm`` mints the id, opens a context for it, and inserts the
    row into its own context. Deleting is not offered; a firm owns clients,
    books and an audit trail, and ``is active`` is what "we stopped" means.

    A new firm's owner is invited, not given a login: the page shows the link once, and a checklist of what has happened since.
    """

    form = FirmForm
    list_display = ("name", "is_active", "member_count", "client_count", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("member_count", "client_count", "created_at")
    inlines = (FirmMembersInline, FirmClientsInline)
    change_form_template = "admin/superadmin/platformfirm/change_form.html"
    add_form_template = "admin/superadmin/platformfirm/add_form.html"

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("name", "owner_name", "owner_email", "is_active", "max_members", "max_clients", "trial_ends_on")
        return (
            "name", "is_active", "suspended_message", "max_members", "max_clients", "trial_ends_on",
            "member_count", "client_count", "created_at",
        )

    def get_inlines(self, request, obj):
        return self.inlines if obj is not None else ()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        name, is_active = form.cleaned_data["name"], form.cleaned_data["is_active"]
        limits = {
            "max_members": form.cleaned_data.get("max_members"),
            "max_clients": form.cleaned_data.get("max_clients"),
            "trial_ends_at": form.trial_end(),
            "suspended_message": form.cleaned_data.get("suspended_message", ""),
        }
        if change:
            service.platform_update_firm(obj.pk, name=name, is_active=is_active)
            service.platform_set_limits(obj.pk, **limits)
            return
        from core.provisioning import create_firm

        created = create_firm(name)
        if not is_active:
            service.platform_update_firm(created.pk, name=name, is_active=False)
        service.platform_set_limits(created.pk, **limits)
        record, link = service.platform_invite_owner(
            created.pk, email=form.cleaned_data["owner_email"], full_name=form.cleaned_data.get("owner_name", "")
        )
        self._show_link_once(request, created.pk, link)
        # The admin redirects to the new row's page and logs the addition by
        # primary key, so it needs to know which firm was made.
        obj.pk = created.pk

    def response_add(self, request, obj, post_url_continue=None):
        """A new firm lands on its own page, where the owner's link is shown once, not back on the list."""
        if "_addanother" not in request.POST:
            request.POST = request.POST.copy()
            request.POST["_continue"] = "1"
        return super().response_add(request, obj, post_url_continue)

    # -- the owner's invitation ------------------------------------------------

    @staticmethod
    def _show_link_once(request, firm_id, link: str) -> None:
        """Keep the link for the next page view only, in the server-side session; it is never stored anywhere else."""
        request.session["owner_link"] = {"firm": str(firm_id), "link": f"{settings.FRONTEND_URL}/invite/{link}"}

    def get_urls(self):
        from django.urls import path

        wrap = self.admin_site.admin_view
        return [
            path("<path:object_id>/owner-link/", wrap(self.owner_link_view), name="superadmin_platformfirm_owner_link"),
            path("<path:object_id>/owner-revoke/", wrap(self.owner_revoke_view), name="superadmin_platformfirm_owner_revoke"),
            *super().get_urls(),
        ]

    def _back(self, object_id):
        return HttpResponseRedirect(reverse("admin:superadmin_platformfirm_change", args=[object_id]))

    def owner_link_view(self, request, object_id):
        """POST: a new link for the owner's invitation, or a first invitation to the address typed."""
        if request.method != "POST" or not self.has_change_permission(request):
            raise PermissionDenied
        try:
            state = service.platform_firm_onboarding(object_id)
            if state["owner_invite_id"]:
                _record, link = service.platform_reissue_invite(state["owner_invite_id"], object_id)
            else:
                email = (request.POST.get("owner_email") or state["owner_invite_email"]).strip()
                _record, link = service.platform_invite_owner(object_id, email=email, full_name=request.POST.get("owner_name", ""))
        except TeamError as exc:
            messages.error(request, "; ".join(exc.messages))
            return self._back(object_id)
        self._show_link_once(request, object_id, link)
        return self._back(object_id)

    def owner_revoke_view(self, request, object_id):
        """POST: cancel the owner's pending invitation."""
        if request.method != "POST" or not self.has_change_permission(request):
            raise PermissionDenied
        state = service.platform_firm_onboarding(object_id)
        if state["owner_invite_id"]:
            service.platform_revoke_invite(state["owner_invite_id"], object_id)
            messages.success(request, "The invitation was cancelled. Its link no longer works.")
        return self._back(object_id)

    @staticmethod
    def _limits_for(object_id) -> list[dict]:
        """People, clients and trial for the firm page's limits card, from the gated stats view."""
        from superadmin.home import _pct, _state

        try:
            stats = PlatformFirmStats.objects.filter(pk=object_id).first()
        except Exception:  # noqa: BLE001 -- the page must open even if the view is not installed
            return []
        if stats is None:
            return []
        now = timezone.now()
        if stats.trial_ends_at is None:
            trial = {"label": "Trial", "text": "None", "pct": None, "state": "", "note": "No trial date is set."}
        elif stats.trial_ends_at < now:
            trial = {"label": "Trial", "text": f"Ended {stats.trial_ends_at:%d %b}", "pct": 100, "state": "full", "note": "Nothing switches off by itself."}
        else:
            trial = {"label": "Trial", "text": f"Ends {stats.trial_ends_at:%d %b}", "pct": None, "state": "", "note": "Nothing switches off by itself."}
        taken = stats.active_members + stats.pending_invites
        return [
            {
                "label": "People",
                "text": f"{taken} of {stats.max_members}" if stats.max_members else str(taken),
                "pct": _pct(taken, stats.max_members),
                "state": _state(taken, stats.max_members),
                "note": "Waiting invitations count toward the limit.",
            },
            {
                "label": "Clients",
                "text": f"{stats.clients} of {stats.max_clients}" if stats.max_clients else str(stats.clients),
                "pct": _pct(stats.clients, stats.max_clients),
                "state": _state(stats.clients, stats.max_clients),
                "note": "The firm cannot add a client past its limit.",
            },
            trial,
        ]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra = dict(extra_context or {})
        shown = request.session.get("owner_link")
        if shown and shown.get("firm") == str(object_id):
            extra["owner_link"] = request.session.pop("owner_link")["link"]
        try:
            extra["onboarding"] = service.platform_firm_onboarding(object_id)
        except Exception:  # noqa: BLE001 -- the page must open even if a count cannot be read
            logging.getLogger("autoca.superadmin").warning("the onboarding panel could not be built", exc_info=True)
            extra["onboarding"] = None
            extra["onboarding_error"] = True
        extra["limits"] = self._limits_for(object_id)
        return super().change_view(request, object_id, form_url, extra)


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
    values = {
        "role": role,
        "manager_id": manager.pk if manager else None,
        "scope_all_clients": bool(data.get("scope_all_clients")),
        "is_active": bool(data.get("membership_active")),
        "make_owner": bool(data.get("make_owner")),
    }

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


# ---------------------------------------------------------------------------
# Invitations across every firm
# ---------------------------------------------------------------------------


@admin.register(PlatformInvite)
class PlatformInviteAdmin(ReadOnlyAdmin):
    """Every firm's invitations in one list: who is waiting, who is stuck, and which ones ran out.

    A link's secret is never stored, so it cannot be shown again. "Make a new link" replaces a waiting or expired invitation with a
    fresh one, whose link is shown once on the page that follows and then forgotten; "Cancel" stops a waiting one.
    """

    list_display = ("email", "firm_name", "role_label", "state", "created_at", "expires_at", "created_by_email")
    list_filter = ("state", "role", "make_owner")
    search_fields = ("email", "firm_name")
    ordering = ("-created_at",)
    actions = ("new_links", "cancel")
    list_per_page = 100

    @admin.display(description="Role", ordering="role")
    def role_label(self, obj):
        return "Firm owner" if obj.make_owner else obj.get_role_display()

    def get_urls(self):
        from django.urls import path

        return [
            path("links/", self.admin_site.admin_view(self.links_view), name="superadmin_platforminvite_links"),
            *super().get_urls(),
        ]

    @admin.action(description="Make a new link for the selected invitations (waiting or expired)")
    def new_links(self, request, queryset):
        made, failed = [], 0
        for invite in queryset.filter(state__in=("pending", "expired")):
            try:
                _record, link = service.platform_reissue_invite(invite.pk, invite.firm_id)
            except TeamError:
                failed += 1
                continue
            made.append({"firm": invite.firm_name, "email": invite.email, "link": f"{settings.FRONTEND_URL}/invite/{link}"})
        if failed:
            messages.warning(request, f"{failed} could not be given a new link.")
        if not made:
            messages.info(request, "Nothing to replace: only waiting or expired invitations can be given a new link.")
            return None
        request.session["invite_links"] = made  # shown once on the next page, in the server-side session
        return HttpResponseRedirect(reverse("admin:superadmin_platforminvite_links"))

    @admin.action(description="Cancel the selected waiting invitations")
    def cancel(self, request, queryset):
        count = 0
        for invite in queryset.filter(state="pending"):
            service.platform_revoke_invite(invite.pk, invite.firm_id)
            count += 1
        messages.success(request, f"{count} invitation{'s' if count != 1 else ''} cancelled. Their links no longer work.")

    def links_view(self, request):
        from django.template.response import TemplateResponse

        links = request.session.pop("invite_links", [])
        context = {**self.admin_site.each_context(request), "title": "New invitation links", "links": links, "opts": self.model._meta}
        return TemplateResponse(request, "admin/superadmin/platforminvite/links.html", context)


# ---------------------------------------------------------------------------
# The platform dashboard: every firm at a glance
# ---------------------------------------------------------------------------

QUIET_DAYS = 14
TRIAL_WARNING_DAYS = 14


class NeedsAttentionFilter(admin.SimpleListFilter):
    title = "needs attention"
    parameter_name = "flag"

    def lookups(self, request, model_admin):
        return (
            ("quiet", f"No activity for {QUIET_DAYS} days"),
            ("trial", "Trial ending or ended"),
            ("full", "At a limit"),
            ("failing", "Failed jobs"),
            ("no_owner", "Owner has not joined"),
        )

    def queryset(self, request, queryset):
        from django.db.models import F, Q

        now = timezone.now()
        value = self.value()
        if value == "quiet":
            return queryset.filter(is_active=True).filter(Q(last_activity__lt=now - datetime.timedelta(days=QUIET_DAYS)) | Q(last_activity__isnull=True))
        if value == "trial":
            return queryset.filter(trial_ends_at__isnull=False, trial_ends_at__lt=now + datetime.timedelta(days=TRIAL_WARNING_DAYS))
        if value == "full":
            taken = queryset.annotate(taken=F("active_members") + F("pending_invites"))
            return taken.filter(
                Q(max_members__isnull=False, taken__gte=F("max_members")) | Q(max_clients__isnull=False, clients__gte=F("max_clients"))
            )
        if value == "failing":
            return queryset.filter(failed_jobs_30d__gt=0)
        if value == "no_owner":
            return queryset.exclude(id__in=PlatformMembership.objects.filter(is_owner=True, is_active=True).values("firm_id"))
        return queryset


@admin.register(PlatformFirmStats)
class PlatformDashboardAdmin(ReadOnlyAdmin):
    """Every firm on one page: people, clients, how lively it has been, what the models cost it, and what is agreed with it.

    Counts, dates and money only. Nothing a firm wrote is here, and nothing can be changed from this page: a firm's own page is
    where its limits, trial and suspension are set.
    """

    list_display = ("name", "in_service", "people", "invites_waiting", "client_count", "statements_this_month", "last_seen", "model_spend", "trial", "failed_jobs_30d")
    list_filter = ("is_active", NeedsAttentionFilter)
    search_fields = ("name",)
    ordering = ("name",)
    list_per_page = 100

    def changelist_view(self, request, extra_context=None):
        self._spend = _spend_by_firm()
        return super().changelist_view(request, extra_context)

    @admin.display(description="In service", boolean=True, ordering="is_active")
    def in_service(self, obj):
        return obj.is_active

    @admin.display(description="People", ordering="active_members")
    def people(self, obj):
        return f"{obj.active_members} / {obj.max_members}" if obj.max_members else str(obj.active_members)

    @admin.display(description="Invites waiting", ordering="pending_invites")
    def invites_waiting(self, obj):
        return obj.pending_invites

    @admin.display(description="Clients", ordering="clients")
    def client_count(self, obj):
        return f"{obj.clients} / {obj.max_clients}" if obj.max_clients else str(obj.clients)

    @admin.display(description="Last activity", ordering="last_activity")
    def last_seen(self, obj):
        if obj.last_activity is None:
            return "never"
        days = (timezone.now() - obj.last_activity).days
        return "today" if days <= 0 else f"{days} day{'s' if days != 1 else ''} ago"

    @admin.display(description="Model spend (30 days)")
    def model_spend(self, obj):
        from usage.pricing import inr

        micro = getattr(self, "_spend", {}).get(str(obj.pk), 0)
        return f"Rs {inr(micro):,.2f}" if micro else "—"

    @admin.display(description="Trial", ordering="trial_ends_at")
    def trial(self, obj):
        if obj.trial_ends_at is None:
            return "—"
        days = (obj.trial_ends_at - timezone.now()).days
        return f"ends in {days} day{'s' if days != 1 else ''}" if days >= 0 else f"ended {-days} day{'s' if days != -1 else ''} ago"


def _spend_by_firm() -> dict[str, int]:
    """What the models cost each firm over the last thirty days, in millionths of a dollar, from the recorded calls."""
    from django.db.models import Sum

    from usage.models import UsageEvent

    since = timezone.now() - datetime.timedelta(days=30)
    rows = UsageEvent.objects.filter(at__gte=since).exclude(firm_id=None).values("firm_id").annotate(cost=Sum("cost_micro_usd"))
    return {str(r["firm_id"]): int(r["cost"] or 0) for r in rows}
