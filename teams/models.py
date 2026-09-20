"""Invitations, the work log, and the history of team changes."""

from __future__ import annotations

import hashlib

from django.db import models

from core.models import FirmMembership, FirmScopedModel, Role, User, UUIDModel


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Invite(UUIDModel, FirmScopedModel):
    """A single-use link that puts a person into the firm.

    Only a hash of the secret is stored. The link carries the firm id as well
    as the secret, because redeeming it happens before anyone is signed in and
    the lookup needs a tenant context to run under.
    """

    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    manager = models.ForeignKey(
        FirmMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    #: Accepting makes this person the firm's owner (only if it has none).
    make_owner = models.BooleanField(default=False)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    accepted_membership = models.ForeignKey(
        FirmMembership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "teams_invite"
        ordering = ["-created_at"]


class ActivityKind(models.TextChoices):
    """Work that leaves no attribution of its own.

    Uploads (``Document.uploaded_by``), approvals and corrections
    (``JournalEntry.approved_by``) are counted straight from those permanent records, so they need no event
    and no backfill. Placement does need one: approval overwrites
    ``reviewed_by`` with the approver, which loses who did the preparing.
    """

    ROW_PLACED = "row.placed", "Rows placed"
    LEDGER_CREATED = "ledger.created", "Ledgers created"
    RULE_CREATED = "rule.created", "Rules written by hand"
    PROPOSAL_DECIDED = "proposal.decided", "Ledger proposals decided"
    MODEL_RUN = "model.run", "Model runs"


class ActivityEvent(UUIDModel, FirmScopedModel):
    """One unit of work somebody did. Append-only.

    Written in the same transaction as the work, so the count and the work
    commit or roll back together. ``quantity`` is how many rows one action
    covered -- placing one row can place eight more through the rule it taught.

    Plain ids rather than foreign keys: an append-only row cannot be updated,
    so ``SET_NULL`` on a deleted client would fail the delete.
    """

    user_id = models.UUIDField(db_index=True)
    client_id = models.UUIDField(null=True, blank=True)
    kind = models.CharField(max_length=32, choices=ActivityKind.choices)
    quantity = models.PositiveIntegerField(default=1)
    subject_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "teams_activity_event"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["firm", "user_id", "created_at"], name="idx_activity_user"),
            models.Index(fields=["firm", "client_id", "created_at"], name="idx_activity_client"),
        ]


class TeamEventKind(models.TextChoices):
    INVITED = "member.invited", "Invited"
    JOINED = "member.joined", "Joined"
    INVITE_REVOKED = "invite.revoked", "Invite revoked"
    ROLE_CHANGED = "member.role_changed", "Role changed"
    OWNER_CHANGED = "firm.owner_changed", "Ownership transferred"
    FIRM_RENAMED = "firm.renamed", "Firm renamed"
    MANAGER_CHANGED = "member.manager_changed", "Moved to another team"
    SCOPE_CHANGED = "member.scope_changed", "All-clients access changed"
    DEACTIVATED = "member.deactivated", "Deactivated"
    #: Taken out of the firm by the platform owner, so they can join another.
    REMOVED = "member.removed", "Removed from firm"
    REACTIVATED = "member.reactivated", "Reactivated"
    LEAD_CHANGED = "client.lead_changed", "Client lead changed"
    ASSIGNED = "client.assigned", "Assigned to client"
    UNASSIGNED = "client.unassigned", "Removed from client"


class TeamEvent(UUIDModel, FirmScopedModel):
    """Who changed the team, and how. Append-only, so ids and name snapshots
    rather than foreign keys (see ActivityEvent)."""

    kind = models.CharField(max_length=32, choices=TeamEventKind.choices)
    actor_id = models.UUIDField(null=True, blank=True)
    member_id = models.UUIDField(null=True, blank=True, db_index=True)
    client_id = models.UUIDField(null=True, blank=True, db_index=True)
    #: Names as they were, plus before/after: {"actor": "...", "member": "...",
    #: "client": "...", "from": "...", "to": "..."}.
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "teams_team_event"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["firm", "-created_at"], name="idx_team_event_firm")]
