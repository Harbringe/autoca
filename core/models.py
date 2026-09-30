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
    #: The Senior CA (or firm admin) responsible for this client, and the only
    #: person besides a firm admin who may sign off its entries. None means no
    #: lead yet, where any approver may sign off, as before leads existed.
    #: Same-firm is enforced by a composite foreign key carrying firm_id; see
    #: core/migrations/0009. A plain foreign key is not subject to RLS and
    #: would accept another firm's membership.
    lead = models.ForeignKey(
        "FirmMembership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_clients",
    )

    #: Everything dated on or before this is locked. Set only by a senior's
    #: sign-off (``ledger.books.sign_off``); until then the books are a working
    #: draft that a CA may change freely. The database refuses any write into a
    #: locked period, and refuses to move this date backwards except through an
    #: explicit reopen -- see ``ledger/migrations/0008``. NULL means nothing has
    #: been signed off yet.
    signed_off_through = models.DateField(null=True, blank=True)

    #: What the client's business is, in the CA's words: "Wholesale cloth trader,
    #: sells to retailers on 30-day credit; rents a godown; two salaried staff".
    #: Read by the model tier so it books a "Sharma Traders" credit as sales
    #: rather than guessing. Free text a person wrote, so it is masked before it
    #: leaves (see ``classify.llm``); the UI tells the CA not to put names or
    #: numbers in it.
    business_profile = models.TextField(blank=True, default="", max_length=2000)

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


class Designation(models.TextChoices):
    """What this person is, professionally. Separate from their role in a firm.

    A role says what the software lets you do; a designation says what you are.
    A Senior CA in one firm and a partner in another are the same designation
    and different roles, and a firm's letterhead cares about the first.
    """

    PARTNER = "PARTNER", "Partner"
    CHARTERED_ACCOUNTANT = "CA", "Chartered Accountant"
    ARTICLE_ASSISTANT = "ARTICLE", "Article assistant"
    ACCOUNTANT = "ACCOUNTANT", "Accountant"
    ADMINISTRATOR = "ADMIN", "Administrator"
    OTHER = "OTHER", "Other"


class Profile(UUIDModel):
    """The person behind an account: who they are, not what they may do.

    Deliberately NOT firm-scoped, for the same reason :class:`User` is not. A
    profile hangs off an account, and an account is resolved before any firm
    context exists. Making this firm-scoped would reintroduce the chicken-and-egg
    the user table exists to avoid.

    The split is worth keeping clear:

    * :class:`User` is the login -- address, password, whether it works.
    * :class:`FirmMembership` is the job -- which firm, what role, whose team.
    * This is the person -- their name as it should be printed, how to reach
      them, and the membership number that goes on filings.

    One row per account, created automatically, so the page is never missing.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    #: How the name should appear on a document, when that differs from the
    #: account's own. Blank means use the account's full name.
    display_name = models.CharField(
        max_length=255, blank=True, help_text="Leave blank to use the account's full name."
    )
    designation = models.CharField(
        max_length=16, choices=Designation.choices, blank=True, default=""
    )
    #: The ICAI membership number a Chartered Accountant signs with. Kept here
    #: rather than on the membership because it belongs to the person, not the
    #: firm they currently work at.
    icai_membership_no = models.CharField(
        max_length=32, blank=True, default="", verbose_name="ICAI membership number"
    )
    phone = models.CharField(max_length=32, blank=True, default="")

    #: A link, not an upload. Uploads in this product go through a tenant-keyed
    #: storage adapter with its own access rules, and an avatar is not worth
    #: bending that around.
    avatar_url = models.URLField(blank=True, default="", verbose_name="Avatar URL")

    timezone = models.CharField(
        max_length=64,
        default="Asia/Kolkata",
        help_text="Used when showing this person dates and times.",
    )
    notes = models.TextField(
        blank=True, default="", help_text="Internal. Visible to the platform owner only."
    )

    class Meta:
        db_table = "core_profile"
        ordering = ["user__email"]

    def __str__(self) -> str:
        return self.name

    @property
    def name(self) -> str:
        """The best name available, in the order a human would pick one."""
        return self.display_name or self.user.full_name or self.user.email


class Role(models.TextChoices):
    """One role per firm-user.

    The split that matters is between preparing and approving. A CA carries
    personal legal responsibility for what is filed, so approval -- the moment a
    suggestion becomes an immutable ledger entry -- is restricted to the two
    senior roles, enforced server-side rather than by hiding a button.

    Intra-firm, per-client RBAC is a later phase. The hook for it is
    ``FirmMembership.scope_all_clients`` plus ``accessible_clients()`` -- adding
    the restriction becomes a migration and a queryset filter rather than a
    rewrite of every call site.
    """

    FIRM_ADMIN = "FIRM_ADMIN", "Firm administrator"
    SENIOR_CA = "SENIOR_CA", "Senior CA"
    STAFF = "STAFF", "Staff"
    READ_ONLY = "READ_ONLY", "Read only"


#: Roles that may turn a suggestion into a posted journal entry.
APPROVER_ROLES = frozenset({Role.FIRM_ADMIN, Role.SENIOR_CA})

#: Roles that may create or edit anything at all.
PREPARER_ROLES = frozenset({Role.FIRM_ADMIN, Role.SENIOR_CA, Role.STAFF})


class FirmMembership(UUIDModel, FirmScopedModel):
    """Binds a user to a firm with exactly one role."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)

    #: True: sees every client in the firm. False: only the clients this member
    #: leads or is assigned to (see core.access). The default stays True so
    #: existing members are unaffected; invitations pass False explicitly.
    scope_all_clients = models.BooleanField(default=True)

    #: The firm's owner: a firm administrator who alone may invite additional
    #: administrators or transfer ownership. Administrators may manage the
    #: roles of other non-owner members. At most one owner per firm.
    is_owner = models.BooleanField(default=False)

    #: The Senior CA (or firm admin) whose team this Staff or Read-only member
    #: is on. None for firm admins and Senior CAs, and for anyone not yet placed
    #: on a team. Same-firm is enforced by a composite foreign key carrying
    #: firm_id; see core/migrations/0009.
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )

    class Meta:
        db_table = "core_firm_membership"
        constraints = [
            # One membership per person, not one per firm: an account belongs to
            # exactly one firm. The platform owner is the exception and has no
            # membership at all, which is what identifies them.
            models.UniqueConstraint(fields=["user"], name="uniq_membership_per_user"),
            models.UniqueConstraint(
                fields=["firm"], condition=models.Q(is_owner=True), name="uniq_owner_per_firm"
            ),
        ]

    def __str__(self) -> str:
        # Read by people: admin dropdowns, inline headers, logs of who was
        # given what. Two raw UUIDs answer no question anyone actually asks, so
        # this loads the account when it has to. The fallback matters as much as
        # the happy path -- a label is rendered in places with no tenant context
        # and after rows are gone, and neither is worth an exception.
        try:
            who = self.user.email
        except Exception:  # noqa: BLE001 - no tenant context, or no row any more
            who = self.user_id
        return f"{who} ({self.get_role_display()})"

    @property
    def can_approve(self) -> bool:
        """A senior: may sign books off. Posting is any CA's (``journal.approve``)."""
        return self.is_active and self.role in APPROVER_ROLES

    @property
    def can_prepare(self) -> bool:
        """May create and edit staged suggestions."""
        return self.is_active and self.role in PREPARER_ROLES

    def accessible_clients(self):
        """Clients this membership may act on. The rule lives in core.access."""
        from core.access import visible_clients

        return visible_clients(self)


class ClientAssignment(UUIDModel, FirmScopedModel):
    """A member put to work on a client.

    Staff and Read-only members see only the clients they are assigned to; a
    Senior CA additionally sees the clients they lead. Written only through
    core.team, which checks that client, member and firm all agree.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="assignments")
    membership = models.ForeignKey(
        FirmMembership, on_delete=models.CASCADE, related_name="assignments"
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "core_client_assignment"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "membership"], name="uniq_assignment_per_client_member"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.membership_id} on {self.client_id}"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class JobStatus(models.TextChoices):
    PENDING = "PENDING", "Queued"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"

    @classmethod
    def terminal(cls) -> set[str]:
        return {cls.SUCCEEDED, cls.FAILED}


class Job(UUIDModel, FirmScopedModel):
    """A unit of work the API reports on rather than blocking for.

    Parsing a statement, classifying it, reconciling a period: all of these are
    slow enough that an HTTP request should not sit on them. The architecture is
    specific about the shape -- 202 Accepted with a job id, and the client
    follows progress separately -- and that shape is a contract with every
    client that will ever be written. Establishing it now costs one table;
    retrofitting it later means changing every call site in a frontend.

    **Work currently runs inline**, inside the request that created the job, and
    the job is already finished by the time the 202 is returned. That is a
    deliberate half-step, not an oversight: the contract is real, the Job row is
    real, and moving execution onto a Celery worker is a change inside
    ``core.jobs.run_job`` rather than a change to the API. What a caller sees
    does not move.

    ``idempotency_key`` is what makes a retried request safe. The architecture
    calls for jobs keyed on something natural -- a statement id and a parser
    version, say -- so that re-running a parse updates its suggestions instead
    of duplicating them.
    """

    kind = models.CharField(max_length=64, help_text="e.g. statement.ingest")
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.PENDING)

    #: Natural key. Two requests carrying the same one are the same job.
    idempotency_key = models.CharField(max_length=255, blank=True)

    progress = models.PositiveSmallIntegerField(default=0)
    #: What the job is doing, in words a person can read while they wait.
    message = models.CharField(max_length=255, blank=True)

    #: Whatever the caller asked for, once there is an answer.
    result = models.JSONField(default=dict, blank=True)
    #: The failure, in the words the domain used. These messages are written for
    #: people -- "Balance chain broke at row 30" -- so they are surfaced rather
    #: than replaced with something generic.
    error = models.TextField(blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs"
    )

    class Meta:
        db_table = "core_job"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_job_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "status"], name="idx_job_firm_status"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} [{self.status}]"

    @property
    def is_finished(self) -> bool:
        return self.status in JobStatus.terminal()


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
