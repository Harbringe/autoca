"""The platform layer: who the platform owner is, and what they can read.

**Who.** A super admin is a Django superuser who belongs to no firm. There is no
table of its own. ``is_superuser`` is the flag, and "no firm" is what separates
the platform operator from a firm's own staff.

**What they read.** The ``Platform*`` models below sit over the views in
``superadmin/sql.py``: one row per firm, membership, client and so on, across
every firm, with directory columns only. They exist so the Django admin can list
and search the platform with ordinary querysets.

They are read-only in three independent ways, because a write through one of
these views would run as a BYPASSRLS role:

* ``managed = False``, so migrations never touch them;
* ``save`` and ``delete`` raise here;
* the database grants the application SELECT on the views and nothing else.

Relations point only at other ``Platform*`` models, never at ``core.Firm``. The
isolation suite treats any non-firm-scoped model with a foreign key to
``core.Firm`` as a table that escaped row-level security, and these are views
the app role cannot write, not tables.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import FirmMembership, JobStatus, Role


def is_superadmin(user) -> bool:
    """Call inside a request (or with the user context set): memberships are under RLS."""
    if not user or not user.is_authenticated or not user.is_active or not user.is_superuser:
        return False
    return not FirmMembership.objects.filter(user=user, is_active=True).exists()


class ReadOnlyView(models.Model):
    """A row from one of the platform views. Never written from Python."""

    class Meta:
        abstract = True
        managed = False

    def save(self, *args, **kwargs):
        raise TypeError(
            f"{type(self).__name__} is a read-only view across firms. Write the real "
            "model inside core.db.session.firm_context instead."
        )

    def delete(self, *args, **kwargs):
        raise TypeError(f"{type(self).__name__} is a read-only view across firms.")


def _view(name: str) -> str:
    # Django quotes db_table as one identifier. Closing and reopening the quote
    # here makes it render as "app"."<name>", a table in the app schema.
    return f'app"."{name}'


def _link(model, related_name="+", **kwargs):
    """A relation between two views: no constraint, nothing cascades.

    Hidden (``+``) unless an admin inline follows it back: an inline's form prefix
    is the reverse accessor's name, and two hidden ones on the same page would
    both get an empty prefix.
    """
    return models.ForeignKey(
        model, on_delete=models.DO_NOTHING, db_constraint=False, related_name=related_name, **kwargs
    )


class PlatformFirm(ReadOnlyView):
    id = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField()
    created_at = models.DateTimeField()
    member_count = models.IntegerField("people")
    client_count = models.IntegerField("clients")

    class Meta(ReadOnlyView.Meta):
        db_table = _view("platform_firms")
        ordering = ["name"]
        verbose_name = "firm"
        verbose_name_plural = "firms"

    def __str__(self) -> str:
        return self.name


class PlatformMembership(ReadOnlyView):
    id = models.UUIDField(primary_key=True)
    firm = _link(PlatformFirm, related_name="memberships")
    firm_name = models.CharField("firm", max_length=255)
    user = _link(settings.AUTH_USER_MODEL)
    email = models.EmailField()
    full_name = models.CharField("name", max_length=255)
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField("active")
    is_owner = models.BooleanField("owner")
    scope_all_clients = models.BooleanField("sees all clients")
    manager_id = models.UUIDField(null=True)
    manager_email = models.EmailField("reports to", null=True)
    created_at = models.DateTimeField("joined")

    class Meta(ReadOnlyView.Meta):
        db_table = _view("platform_memberships")
        ordering = ["firm_name", "email"]
        verbose_name = "firm membership"
        verbose_name_plural = "firm memberships"

    def __str__(self) -> str:
        return f"{self.email} ({self.get_role_display()}, {self.firm_name})"


class PlatformClient(ReadOnlyView):
    id = models.UUIDField(primary_key=True)
    firm = _link(PlatformFirm, related_name="clients")
    firm_name = models.CharField("firm", max_length=255)
    name = models.CharField(max_length=255)
    fy_start = models.DateField("financial year starts")
    business_profile = models.TextField("what the business does")
    lead = _link(PlatformMembership, null=True)
    lead_email = models.EmailField("lead", null=True)
    created_at = models.DateTimeField()
    team_size = models.IntegerField("assigned")
    bank_account_count = models.IntegerField("bank accounts")
    statement_count = models.IntegerField("statements")

    class Meta(ReadOnlyView.Meta):
        db_table = _view("platform_clients")
        ordering = ["firm_name", "name"]
        verbose_name = "client"
        verbose_name_plural = "clients"

    def __str__(self) -> str:
        return self.name


class PlatformClientAssignment(ReadOnlyView):
    id = models.UUIDField(primary_key=True)
    firm = _link(PlatformFirm)
    client = _link(PlatformClient, related_name="assignments")
    client_name = models.CharField("client", max_length=255)
    membership = _link(PlatformMembership)
    user = _link(settings.AUTH_USER_MODEL)
    email = models.EmailField()
    created_at = models.DateTimeField()

    class Meta(ReadOnlyView.Meta):
        db_table = _view("platform_client_assignments")
        ordering = ["client_name"]


class PlatformAuditLog(ReadOnlyView):
    id = models.UUIDField(primary_key=True)
    firm = _link(PlatformFirm, null=True)
    firm_name = models.CharField("firm", max_length=255, null=True)
    user = _link(settings.AUTH_USER_MODEL, null=True)
    user_email = models.EmailField("user", null=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=512)
    status_code = models.PositiveSmallIntegerField("status")
    ip_address = models.GenericIPAddressField("IP address", null=True)
    request_id = models.CharField(max_length=64)
    duration_ms = models.PositiveIntegerField("ms", null=True)
    created_at = models.DateTimeField("when")

    class Meta(ReadOnlyView.Meta):
        db_table = _view("platform_audit_log")
        ordering = ["-created_at"]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit logs"


class PlatformJob(ReadOnlyView):
    id = models.UUIDField(primary_key=True)
    firm = _link(PlatformFirm)
    firm_name = models.CharField("firm", max_length=255)
    kind = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=JobStatus.choices)
    progress = models.PositiveSmallIntegerField()
    message = models.CharField(max_length=255)
    error_code = models.CharField(max_length=64)
    created_by = _link(settings.AUTH_USER_MODEL, null=True)
    created_by_email = models.EmailField("started by", null=True)
    created_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta(ReadOnlyView.Meta):
        db_table = _view("platform_jobs")
        ordering = ["-created_at"]
        verbose_name = "job"
        verbose_name_plural = "jobs"
