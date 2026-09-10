"""Tenancy root, users, RBAC, and the audit trail.

Model rules for this codebase:

* Anything that belongs to a firm subclasses :class:`FirmScopedModel`. That is
  not a convenience -- it is how the isolation test suite discovers tables to
  attack. A model with a ``firm`` foreign key that does not subclass it fails
  ``core.tests.test_rls_isolation`` by design.
* :class:`Firm` is the tenant root and is itself RLS-protected, so a firm can
  read exactly one row of it: its own.
* :class:`User` is deliberately NOT firm-scoped. Login resolves an email
  address before any firm context can exist; making the user table
  firm-scoped would create a chicken-and-egg problem that could only be
  resolved by an RLS bypass, and a bypass that exists for login will
  eventually be used for something else.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class UUIDModel(models.Model):
    """UUID primary keys throughout.

    Sequential integer ids across a tenant boundary leak volume and ordering
    information, and make an IDOR bug trivially exploitable by incrementing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True


class Firm(UUIDModel):
    """A CA firm. The tenant root: every isolation boundary is drawn here."""

    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "core_firm"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FirmScopedModel(models.Model):
    """Base class for every table that holds one firm's data.

    Subclassing this is the contract that gets a table an RLS policy and gets it
    enrolled in the cross-tenant isolation suite.
    """

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="%(class)ss")

    class Meta:
        abstract = True


class Client(UUIDModel, FirmScopedModel):
    """A client of a firm. The firm's customer -- one level below the tenant root."""

    name = models.CharField(max_length=255)
    fy_start = models.DateField(
        help_text="First day of the client's financial year, e.g. 2026-04-01.",
    )

    class Meta:
        db_table = "core_client"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["firm", "name"], name="uniq_client_name_per_firm"),
        ]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Users, roles
# ---------------------------------------------------------------------------


class UserManager(BaseUserManager):
    use_in_migrations = False

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create(email, password, **extra)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """A person. Not firm-scoped; see the module docstring.

    ``is_superuser`` here is Django-admin power only. It confers no ability to
    read another firm's rows, because cross-tenant reads are blocked at the
    database by a policy the application's database role cannot turn off.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "core_user"

    def __str__(self) -> str:
        return self.email

    @property
    def has_mfa(self) -> bool:
        """True once at least one confirmed TOTP device exists."""
        from django_otp.plugins.otp_totp.models import TOTPDevice

        return TOTPDevice.objects.filter(user=self, confirmed=True).exists()


class Role(models.TextChoices):
    """One role per firm-user, for now.

    Intra-firm, per-client RBAC is a later phase. The hook for it is
    ``FirmMembership.scope_all_clients`` plus ``accessible_clients()`` -- adding
    the restriction becomes a migration and a queryset filter rather than a
    rewrite of every call site.
    """

    OWNER = "OWNER", "Owner"
    STAFF = "STAFF", "Staff"


class FirmMembership(UUIDModel, FirmScopedModel):
    """Binds a user to a firm with exactly one role."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)

    #: Forward hook for per-client RBAC. True means "every client in the firm",
    #: which is the only behaviour implemented today. When per-client scoping
    #: lands, False will mean "only the clients listed in the scope table".
    scope_all_clients = models.BooleanField(default=True)

    class Meta:
        db_table = "core_firm_membership"
        constraints = [
            models.UniqueConstraint(fields=["firm", "user"], name="uniq_membership_per_firm_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.firm_id} ({self.role})"

    def accessible_clients(self):
        """Clients this membership may act on.

        Always firm-filtered, never trusting RLS alone. Defence in depth: RLS is
        the wall, this is the lock on the door. If one is ever misconfigured the
        other still holds.
        """
        qs = Client.objects.filter(firm_id=self.firm_id)
        if self.scope_all_clients:
            return qs
        return qs.none()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditLog(UUIDModel, FirmScopedModel):
    """Append-only record of who touched what.

    Intentionally coarse for now -- one row per mutating request. The point of
    building it in this phase is that the hook point exists before any feature
    code lands, so nothing ever gets written that is not covered.
    """

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_entries"
    )
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=512)
    status_code = models.PositiveSmallIntegerField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "core_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["firm", "-created_at"], name="idx_audit_firm_created"),
        ]

    def __str__(self) -> str:
        return f"{self.method} {self.path} -> {self.status_code}"

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit entries are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit entries are append-only and cannot be deleted.")
