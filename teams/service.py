"""Changing the team: invites, reporting lines, client leads and assignments.

Every write goes through here, and every function takes the acting membership
first. The reporting chain is owner -> firm administrators -> Senior CAs ->
Staff and Read-only members. The owner manages administrator invitations and
ownership transfer; administrators manage everyone except the owner; a Senior
CA manages roles and access for their own direct reports.

Nobody is left orphaned: a Senior CA who still leads clients or has a team
cannot be deactivated or demoted until those are handed over.

Foreign keys are checked for same-firm here, because PostgreSQL checks
referential integrity without RLS and would accept another firm's row.
"""

from __future__ import annotations

import datetime
import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import APPROVER_ROLES, Client, ClientAssignment, FirmMembership, Role, User
from teams.models import Invite, TeamEvent, TeamEventKind, hash_token

INVITE_LIFETIME = datetime.timedelta(days=7)
TEAM_ROLES = frozenset({Role.STAFF, Role.READ_ONLY})
LEAD_ROLES = APPROVER_ROLES  # Senior CA, firm admin


class TeamError(ValidationError):
    """A request that breaks a team rule. Carries a sentence for the person."""


# ---------------------------------------------------------------------------
# Who may do what to whom
# ---------------------------------------------------------------------------


def is_admin(actor: FirmMembership) -> bool:
    return actor.is_active and actor.role == Role.FIRM_ADMIN


def is_lead(actor: FirmMembership) -> bool:
    return actor.is_active and actor.role == Role.SENIOR_CA


def firm_owner(firm_id) -> FirmMembership | None:
    return FirmMembership.objects.filter(firm_id=firm_id, is_owner=True).select_related("user").first()


def can_manage_admins(actor: FirmMembership) -> bool:
    """Who may invite another administrator or transfer firm ownership."""
    if not is_admin(actor):
        return False
    return actor.is_owner or not FirmMembership.objects.filter(firm_id=actor.firm_id, is_owner=True).exists()


def role_label(membership: FirmMembership) -> str:
    return "Firm owner" if membership.is_owner else membership.get_role_display()


def label(membership: FirmMembership | None) -> str:
    if membership is None:
        return "nobody"
    user = membership.user
    return user.full_name or user.email


def visible_members(actor: FirmMembership):
    members = FirmMembership.objects.filter(firm_id=actor.firm_id).select_related(
        "user", "manager__user"
    )
    if is_admin(actor):
        return members if actor.is_owner else members.exclude(is_owner=True)
    if is_lead(actor):
        return members.filter(Q(pk=actor.pk) | Q(manager=actor))
    return members.filter(pk=actor.pk)


def can_view_member(actor: FirmMembership, target: FirmMembership) -> bool:
    return visible_members(actor).filter(pk=target.pk).exists()


def _same_firm(actor: FirmMembership, *objects) -> None:
    for obj in objects:
        if obj is not None and obj.firm_id != actor.firm_id:
            # Indistinguishable from "does not exist", on purpose.
            raise TeamError("Not found.")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PermissionDenied(message)


def _valid_manager(actor: FirmMembership, manager: FirmMembership | None) -> None:
    if manager is None:
        return
    _same_firm(actor, manager)
    if not manager.is_active or manager.role not in LEAD_ROLES:
        raise TeamError("A reporting line has to point to an active manager in the firm.")


def _valid_parent(actor: FirmMembership, child_role: str, manager: FirmMembership | None) -> None:
    """Keep the reporting chain owner -> admin -> senior -> staff/read-only."""
    if manager is None:
        if child_role in {Role.SENIOR_CA, Role.STAFF, Role.READ_ONLY} or firm_owner(actor.firm_id):
            raise TeamError("Assign an active manager at the level directly above this role.")
        return
    _valid_manager(actor, manager)
    allowed = {
        Role.FIRM_ADMIN: manager.is_owner,
        Role.SENIOR_CA: manager.role == Role.FIRM_ADMIN,
        Role.STAFF: manager.role == Role.SENIOR_CA,
        Role.READ_ONLY: manager.role == Role.SENIOR_CA,
    }
    if not allowed.get(child_role, False):
        raise TeamError("Choose a manager from the level directly above this role.")


def _active_admins(firm_id) -> int:
    return FirmMembership.objects.filter(
        firm_id=firm_id, role=Role.FIRM_ADMIN, is_active=True
    ).count()


def _handover_needed(target: FirmMembership) -> str | None:
    reports = FirmMembership.objects.filter(manager=target, is_active=True).count()
    led = Client.objects.filter(lead=target).count()
    if not reports and not led:
        return None
    parts = []
    if reports:
        parts.append(f"{reports} team member{'s' if reports != 1 else ''}")
    if led:
        parts.append(f"{led} client{'s' if led != 1 else ''}")
    return (
        f"{label(target)} still leads {' and '.join(parts)}. Move them to someone else first."
    )


def _event(actor, kind, *, member=None, client=None, **detail) -> None:
    TeamEvent.objects.create(
        firm_id=actor.firm_id,
        kind=kind,
        actor_id=actor.user_id,
        member_id=getattr(member, "pk", None),
        client_id=getattr(client, "pk", None),
        detail={
            "actor": label(actor),
            **({"member": label(member)} if member is not None else {}),
            **({"client": client.name} if client is not None else {}),
            **detail,
        },
    )


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@transaction.atomic
def invite(
    actor: FirmMembership,
    *,
    email: str,
    full_name: str = "",
    role: str = Role.STAFF,
    manager: FirmMembership | None = None,
) -> tuple[Invite, str]:
    """Returns the invite and the link secret. The secret is never stored."""
    if is_lead(actor):
        _require(role in TEAM_ROLES, "A Senior CA can invite Staff and Read-only members.")
        manager = actor
    else:
        _require(is_admin(actor), "Only a firm administrator or Senior CA can invite people.")
        if role == Role.FIRM_ADMIN:
            _require(can_manage_admins(actor), "Only the firm owner can add another firm administrator.")
        if role in LEAD_ROLES:
            manager = None
    if role == Role.FIRM_ADMIN:
        manager = firm_owner(actor.firm_id) if not actor.is_owner else actor
    elif role == Role.SENIOR_CA and manager is None and is_admin(actor):
        manager = actor
    elif role in TEAM_ROLES and is_lead(actor):
        manager = actor
    _valid_parent(actor, role, manager)
    return issue_invite(
        actor.firm_id,
        email=email,
        full_name=full_name,
        role=role,
        manager=manager,
        created_by=actor.user,
        actor_label=label(actor),
    )


def issue_invite(
    firm_id,
    *,
    email: str,
    full_name: str = "",
    role: str,
    manager: FirmMembership | None = None,
    created_by: User | None,
    actor_label: str,
    make_owner: bool = False,
) -> tuple[Invite, str]:
    """Create the invite under ``firm_id``'s tenant context, which the caller holds.

    The permission decision is the caller's: :func:`invite` for people inside
    the firm, the super admin console for a firm's first administrators.
    """
    email = email.strip().lower()
    if role not in Role.values:
        raise TeamError("Not a role.")
    if make_owner:
        role = Role.FIRM_ADMIN
        if FirmMembership.objects.filter(firm_id=firm_id, is_owner=True).exists():
            raise TeamError("This firm already has an owner. They can transfer ownership from Firm settings.")
    if FirmMembership.objects.filter(firm_id=firm_id, user__email=email, is_active=True).exists():
        raise TeamError(f"{email} is already in the firm.")

    # One live invite per address: a new one replaces any earlier link.
    Invite.objects.filter(
        firm_id=firm_id, email=email, used_at__isnull=True, revoked_at__isnull=True
    ).update(revoked_at=timezone.now())

    secret = secrets.token_urlsafe(32)
    record = Invite.objects.create(
        firm_id=firm_id,
        email=email,
        full_name=full_name.strip(),
        role=role,
        manager=manager if not make_owner else None,
        make_owner=make_owner,
        token_hash=hash_token(secret),
        expires_at=timezone.now() + INVITE_LIFETIME,
        created_by=created_by,
    )
    TeamEvent.objects.create(
        firm_id=firm_id,
        kind=TeamEventKind.INVITED,
        actor_id=getattr(created_by, "pk", None),
        detail={
            "actor": actor_label,
            "email": email,
            "role": "Firm owner" if make_owner else Role(role).label,
            "to": label(manager) if manager else "",
        },
    )
    return record, f"{firm_id}.{secret}"


def visible_invites(actor: FirmMembership):
    invites = Invite.objects.filter(
        firm_id=actor.firm_id, used_at__isnull=True, revoked_at__isnull=True
    ).select_related("manager__user", "created_by")
    if is_admin(actor):
        return invites if actor.is_owner else invites.exclude(make_owner=True)
    return invites.filter(created_by=actor.user)


@transaction.atomic
def revoke_invite(actor: FirmMembership, record: Invite) -> None:
    _same_firm(actor, record)
    _require(
        is_admin(actor) or record.created_by_id == actor.user_id,
        "Only the person who sent this invite or a firm administrator can revoke it.",
    )
    record.revoked_at = timezone.now()
    record.save(update_fields=["revoked_at"])
    _event(actor, TeamEventKind.INVITE_REVOKED, email=record.email)


def split_link(link: str) -> tuple[str, str] | None:
    firm_id, _, secret = (link or "").partition(".")
    if not firm_id or not secret:
        return None
    return firm_id, secret


def find_invite(secret: str) -> Invite | None:
    """Under the invite's firm context, set by the caller."""
    return (
        Invite.objects.select_for_update(of=("self",))
        .filter(token_hash=hash_token(secret))
        .select_related("manager")
        .first()
    )


def invite_problem(record: Invite | None) -> str | None:
    if record is None or record.revoked_at is not None:
        return "This invite link isn't valid. Ask for a new one."
    if record.used_at is not None:
        return "This invite has already been used. Sign in instead."
    if record.expires_at <= timezone.now():
        return "This invite has expired. Ask for a new one."
    return None


def accept(record: Invite, *, full_name: str, password: str, existing_user: User | None) -> FirmMembership:
    """Run inside a transaction holding the invite's row lock.

    ``existing_user`` is set only after the caller has checked that account's
    own password: an invite never sets the password of an account that exists.
    """
    if existing_user is None:
        if User.objects.filter(email=record.email).exists():
            raise TeamError("This email already has an AutoCA account. Enter its password.")
        validate_password(password)
        user = User.objects.create_user(
            email=record.email, password=password, full_name=(full_name or record.full_name).strip()
        )
    else:
        user = existing_user

    becomes_owner = (
        record.make_owner
        and not FirmMembership.objects.filter(firm_id=record.firm_id, is_owner=True).exclude(user=user).exists()
    )
    manager = record.manager if record.manager and record.manager.is_active and record.manager.firm_id == record.firm_id else None
    if becomes_owner:
        manager = None
    elif record.role == Role.FIRM_ADMIN:
        manager = firm_owner(record.firm_id)
        if manager is not None and manager.user_id == user.pk:
            raise TeamError("Ask the firm owner to send a fresh administrator invitation.")
        if manager is not None and not manager.is_active:
            raise TeamError("The firm's owner is inactive. Ask for a new administrator invitation.")
    elif record.role == Role.SENIOR_CA:
        if manager is None or manager.role != Role.FIRM_ADMIN:
            manager = firm_owner(record.firm_id)
        if manager is None or not manager.is_active:
            raise TeamError("This invitation no longer has an active administrator to report to. Ask for a new invite.")
    elif record.role in TEAM_ROLES:
        if manager is None or manager.role != Role.SENIOR_CA:
            raise TeamError("This invitation no longer has an active Senior CA to report to. Ask for a new invite.")
    try:
        membership, _ = FirmMembership.objects.update_or_create(
            firm_id=record.firm_id,
            user=user,
            defaults={
                "role": record.role,
                "is_active": True,
                "manager": manager if record.role != Role.FIRM_ADMIN or not becomes_owner else None,
                "scope_all_clients": record.role == Role.FIRM_ADMIN,
                "is_owner": becomes_owner,
            },
        )
    except IntegrityError as exc:
        # An account belongs to exactly one firm (core/migrations/0009). If this
        # one already belongs to another, the lookup above cannot see it -- that
        # membership is another firm's row and row-level security hides it --
        # so the unique index is what answers, and it answers in SQL. Saying so
        # plainly beats an IntegrityError reaching the caller.
        raise TeamError(
            "This account already belongs to another firm. An account belongs to "
            "one firm, so this person needs a separate address here."
        ) from exc
    record.used_at = timezone.now()
    record.accepted_membership = membership
    record.save(update_fields=["used_at", "accepted_membership"])
    TeamEvent.objects.create(
        firm_id=record.firm_id,
        kind=TeamEventKind.JOINED,
        actor_id=user.pk,
        member_id=membership.pk,
        detail={"actor": label(membership), "member": label(membership), "role": role_label(membership)},
    )
    return membership


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@transaction.atomic
def update_member(
    actor: FirmMembership,
    target: FirmMembership,
    *,
    role: str | None = None,
    manager: FirmMembership | None | type[...] = ...,
    scope_all_clients: bool | None = None,
    is_active: bool | None = None,
    keep_client_assignments: bool = False,
) -> FirmMembership:
    _same_firm(actor, target)
    target = FirmMembership.objects.select_for_update(of=("self",)).select_related("user").get(pk=target.pk)
    if target.is_owner and target.pk != actor.pk and (role is not None or is_active is not None):
        raise TeamError(
            "The firm owner can't be changed or deactivated here. The owner can transfer ownership "
            "from Firm settings; otherwise ask the AutoCA super admin."
        )
    touches_admin = target.role == Role.FIRM_ADMIN or role == Role.FIRM_ADMIN
    if touches_admin and (role not in (None, target.role) or is_active is not None):
        _require(is_admin(actor) and not target.is_owner, "Only an administrator can manage another administrator; the firm owner is protected.")

    if role is not None and role != target.role:
        may_manage_team_role = (
            is_lead(actor)
            and target.manager_id == actor.pk
            and target.role in TEAM_ROLES
            and role in TEAM_ROLES
        )
        _require(is_admin(actor) or may_manage_team_role, "You can change roles only within your authority.")
        if role not in Role.values:
            raise TeamError("Not a role.")
        if target.pk == actor.pk:
            raise TeamError("You can't change your own role. Ask the firm owner.")
        if target.role == Role.FIRM_ADMIN and target.is_active and _active_admins(actor.firm_id) <= 1:
            raise TeamError("The firm needs at least one active firm administrator.")
        if target.role in LEAD_ROLES and role in TEAM_ROLES and (problem := _handover_needed(target)):
            raise TeamError(problem)
        before = role_label(target)
        target.role = role
        if role == Role.FIRM_ADMIN:
            target.manager = firm_owner(actor.firm_id)
        elif role == Role.SENIOR_CA:
            if manager is not ...:
                target.manager = manager
            else:
                target.manager = target.manager if target.manager_id and target.manager.role == Role.FIRM_ADMIN else (actor if is_admin(actor) else firm_owner(actor.firm_id))
        elif role in TEAM_ROLES and target.manager_id and target.manager.role != Role.SENIOR_CA:
            target.manager = manager if manager is not ... else (actor if is_lead(actor) else None)
        elif role in TEAM_ROLES and manager is not ...:
            target.manager = manager
        if role in {Role.FIRM_ADMIN, Role.SENIOR_CA, Role.STAFF, Role.READ_ONLY}:
            _valid_parent(actor, role, target.manager)
        target.save(update_fields=["role", "manager"])
        _event(actor, TeamEventKind.ROLE_CHANGED, member=target, **{"from": before, "to": target.get_role_display()})

    if manager is not ...:
        _require(is_admin(actor), "Only a firm administrator can move someone to another team.")
        if target.role == Role.FIRM_ADMIN:
            _require(not target.is_owner, "The firm owner's reporting line cannot be changed.")
        if target.role != Role.FIRM_ADMIN or not target.is_owner:
            _valid_parent(actor, target.role, manager)
        if manager != target.manager:
            old = target.manager
            removed = 0
            if old is not None and not keep_client_assignments:
                removed, _ = ClientAssignment.objects.filter(
                    membership=target, client__lead=old
                ).delete()
            target.manager = manager
            target.save(update_fields=["manager"])
            _event(
                actor,
                TeamEventKind.MANAGER_CHANGED,
                member=target,
                removed_from_clients=removed,
                **{"from": label(old), "to": label(manager)},
            )

    if scope_all_clients is not None and scope_all_clients != target.scope_all_clients:
        _require(is_admin(actor), "Only a firm administrator can change access to all clients.")
        target.scope_all_clients = scope_all_clients
        target.save(update_fields=["scope_all_clients"])
        _event(actor, TeamEventKind.SCOPE_CHANGED, member=target, to="on" if scope_all_clients else "off")

    if is_active is not None and is_active != target.is_active:
        own_team = is_lead(actor) and target.manager_id == actor.pk
        _require(
            is_admin(actor) or own_team,
            "You can switch access on and off only for people on your own team.",
        )
        if target.pk == actor.pk:
            raise TeamError("You can't deactivate yourself.")
        if not is_active:
            if target.role == Role.FIRM_ADMIN and _active_admins(actor.firm_id) <= 1:
                raise TeamError("The firm needs at least one active firm administrator.")
            if problem := _handover_needed(target):
                raise TeamError(problem)
        target.is_active = is_active
        target.save(update_fields=["is_active"])
        _event(actor, TeamEventKind.REACTIVATED if is_active else TeamEventKind.DEACTIVATED, member=target)

    return target


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def managed_clients(actor: FirmMembership):
    clients = Client.objects.filter(firm_id=actor.firm_id).select_related("lead__user")
    if is_admin(actor):
        return clients
    if is_lead(actor):
        return clients.filter(lead=actor)
    return clients.none()


@transaction.atomic
def set_lead(actor: FirmMembership, client: Client, lead: FirmMembership | None) -> Client:
    _same_firm(actor, client, lead)
    _require(is_admin(actor), "Only a firm administrator can change who leads a client.")
    if lead is not None and (not lead.is_active or lead.role not in LEAD_ROLES):
        raise TeamError("A client has to be led by an active Senior CA or firm administrator.")
    if client.lead_id == getattr(lead, "pk", None):
        return client
    old = client.lead
    client.lead = lead
    client.save(update_fields=["lead"])
    _event(actor, TeamEventKind.LEAD_CHANGED, client=client, **{"from": label(old), "to": label(lead)})
    return client


def _may_assign(actor: FirmMembership, client: Client, member: FirmMembership) -> None:
    _same_firm(actor, client, member)
    if is_admin(actor):
        return
    _require(
        is_lead(actor) and client.lead_id == actor.pk,
        "You can assign people only to clients you lead.",
    )
    _require(member.manager_id == actor.pk, "You can assign only people on your own team.")


@transaction.atomic
def assign(actor: FirmMembership, client: Client, member: FirmMembership) -> ClientAssignment:
    _may_assign(actor, client, member)
    if not member.is_active:
        raise TeamError(f"{label(member)} is deactivated.")
    if member.role == Role.FIRM_ADMIN:
        raise TeamError("Firm administrators already see every client.")
    record, created = ClientAssignment.objects.get_or_create(
        firm_id=actor.firm_id, client=client, membership=member, defaults={"assigned_by": actor.user}
    )
    if created:
        _event(actor, TeamEventKind.ASSIGNED, member=member, client=client)
    return record


@transaction.atomic
def unassign(actor: FirmMembership, client: Client, member: FirmMembership) -> None:
    _may_assign(actor, client, member)
    deleted, _ = ClientAssignment.objects.filter(client=client, membership=member).delete()
    if deleted:
        _event(actor, TeamEventKind.UNASSIGNED, member=member, client=client)


def visible_events(actor: FirmMembership):
    events = TeamEvent.objects.filter(firm_id=actor.firm_id)
    if actor.is_owner:
        return events
    owner = firm_owner(actor.firm_id)
    if owner:
        events = events.exclude(actor_id=owner.user_id).exclude(member_id=owner.pk)
    if is_admin(actor):
        return events
    team = list(FirmMembership.objects.filter(manager=actor).values_list("pk", flat=True))
    clients = list(Client.objects.filter(lead=actor).values_list("pk", flat=True))
    return events.filter(
        Q(actor_id=actor.user_id) | Q(member_id__in=[actor.pk, *team]) | Q(client_id__in=clients)
    )


# ---------------------------------------------------------------------------
# The firm itself
# ---------------------------------------------------------------------------


@transaction.atomic
def transfer_ownership(actor: FirmMembership, new_owner: FirmMembership, *, by_superadmin: str = "") -> FirmMembership:
    """Hand ownership to an active firm administrator. The old owner stays an administrator.

    ``by_superadmin`` is set (to the console's label) when the AutoCA super admin
    does this from outside the firm; ``actor`` is then ignored for permission.
    """
    if not by_superadmin:
        _same_firm(actor, new_owner)
        _require(can_manage_admins(actor), "Only the firm owner can transfer ownership.")
    new_owner = FirmMembership.objects.select_for_update(of=("self",)).select_related("user").get(pk=new_owner.pk)
    if not new_owner.is_active or new_owner.role != Role.FIRM_ADMIN:
        raise TeamError("Make them an active firm administrator first; only an administrator can own the firm.")
    old = FirmMembership.objects.filter(firm_id=new_owner.firm_id, is_owner=True).select_related("user").first()
    if old is not None and old.pk == new_owner.pk:
        return new_owner
    if old is not None:
        old.is_owner = False
        old.manager = new_owner
        old.save(update_fields=["is_owner", "manager"])
    new_owner.is_owner = True
    new_owner.manager = None
    new_owner.save(update_fields=["is_owner", "manager"])
    TeamEvent.objects.create(
        firm_id=new_owner.firm_id,
        kind=TeamEventKind.OWNER_CHANGED,
        actor_id=None if by_superadmin else actor.user_id,
        member_id=new_owner.pk,
        detail={
            "actor": by_superadmin or label(actor),
            "member": label(new_owner),
            "from": label(old),
            "to": label(new_owner),
        },
    )
    return new_owner


@transaction.atomic
def rename_firm(actor: FirmMembership, name: str):
    from core.models import Firm

    _require(is_admin(actor), "Only the firm owner or an administrator can rename the firm.")
    name = name.strip()
    if len(name) < 2:
        raise TeamError("Give the firm a name.")
    firm = Firm.objects.get(pk=actor.firm_id)
    before = firm.name
    if before == name:
        return firm
    firm.name = name
    firm.save(update_fields=["name"])
    TeamEvent.objects.create(
        firm_id=firm.pk,
        kind=TeamEventKind.FIRM_RENAMED,
        actor_id=actor.user_id,
        detail={"actor": label(actor), "from": before, "to": name},
    )
    return firm


# ---------------------------------------------------------------------------
# The platform owner
#
# The AutoCA platform owner belongs to no firm, so there is no acting membership
# to check permissions against. What they may do is decided before these are
# called (only a platform owner reaches the Django admin). What these keep is
# every rule that protects the firm itself: it always has an active
# administrator, nobody is left leading a team or clients that have nowhere to
# go, and a team leader is an active Senior CA or administrator of the same firm.
#
# Each opens the context of the one firm it changes. ``firm_context`` clears
# itself on the way out, so a caller can remove someone from one firm and add
# them to another inside a single transaction.
# ---------------------------------------------------------------------------

PLATFORM_ACTOR = "AutoCA platform"


def _platform_event(firm_id, kind, *, member: FirmMembership, **detail) -> None:
    TeamEvent.objects.create(
        firm_id=firm_id,
        kind=kind,
        actor_id=None,
        member_id=member.pk,
        detail={"actor": PLATFORM_ACTOR, "member": label(member), **detail},
    )


def _platform_manager(firm_id, target_role: str, manager_id) -> FirmMembership | None:
    """Resolve a direct report's manager inside the firm, or refuse clearly."""
    expected = {
        Role.FIRM_ADMIN: Role.FIRM_ADMIN,
        Role.SENIOR_CA: Role.FIRM_ADMIN,
        Role.STAFF: Role.SENIOR_CA,
        Role.READ_ONLY: Role.SENIOR_CA,
    }.get(target_role)
    if expected is None:
        raise TeamError("Not a role.")
    # Looked up inside this firm's context, so another firm's membership is
    # simply not found. The composite key in core/migrations/0009 would refuse
    # it anyway.
    manager = None
    if manager_id:
        manager = FirmMembership.objects.filter(firm_id=firm_id, pk=manager_id).select_related("user").first()
    elif target_role == Role.FIRM_ADMIN:
        manager = firm_owner(firm_id)
    elif target_role == Role.SENIOR_CA:
        managers = FirmMembership.objects.filter(firm_id=firm_id, role=expected, is_active=True)
        manager = managers.order_by("-is_owner", "created_at").first()
    if manager is None:
        if target_role == Role.FIRM_ADMIN and not firm_owner(firm_id):
            return None
        raise TeamError("Assign an active manager at the level directly above this role.")
    if not manager.is_active or manager.role != expected:
        raise TeamError("Choose an active manager from the level directly above this role.")
    if target_role == Role.FIRM_ADMIN and not manager.is_owner:
        raise TeamError("A firm administrator reports to the firm owner.")
    return manager


def platform_assign(
    user: User,
    firm_id,
    *,
    role: str = Role.STAFF,
    manager_id=None,
    scope_all_clients: bool | None = None,
) -> FirmMembership:
    """Put a person in a firm. An account belongs to one firm, so they must have none."""
    from core.db.session import firm_context

    if role not in Role.values:
        raise TeamError("Not a role.")
    with firm_context(firm_id):
        manager = _platform_manager(firm_id, role, manager_id)
        if scope_all_clients is None:
            scope_all_clients = role == Role.FIRM_ADMIN
        try:
            with transaction.atomic():
                membership = FirmMembership.objects.create(
                    firm_id=firm_id,
                    user=user,
                    role=role,
                    manager=manager,
                    scope_all_clients=scope_all_clients,
                )
        except IntegrityError as exc:
            raise TeamError(
                "This person already belongs to a firm. Take them out of it first; "
                "an account belongs to one firm."
            ) from exc
        _platform_event(firm_id, TeamEventKind.JOINED, member=membership, role=role_label(membership))
        return membership


def platform_update(
    membership_id,
    firm_id,
    *,
    role: str,
    manager_id,
    scope_all_clients: bool,
    is_active: bool,
    make_owner: bool,
) -> FirmMembership:
    """Change a person's place in their firm, keeping the firm's own rules."""
    from core.db.session import firm_context

    if role not in Role.values:
        raise TeamError("Not a role.")
    with firm_context(firm_id), transaction.atomic():
        target = (
            FirmMembership.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(firm_id=firm_id, pk=membership_id)
            .first()
        )
        if target is None:
            raise TeamError("That membership no longer exists.")

        if target.is_owner and (role != target.role or not is_active):
            raise TeamError(
                "The firm owner must stay an active administrator. Make someone else "
                "the owner first."
            )
        leaves_admin = target.role == Role.FIRM_ADMIN and target.is_active and (
            role != Role.FIRM_ADMIN or not is_active
        )
        if leaves_admin and _active_admins(firm_id) <= 1:
            raise TeamError("The firm needs at least one active firm administrator.")
        steps_down = target.role in LEAD_ROLES and (role in TEAM_ROLES or not is_active)
        if steps_down and (problem := _handover_needed(target)):
            raise TeamError(problem)

        manager = None if target.is_owner else _platform_manager(firm_id, role, manager_id)
        if manager is not None and manager.pk == target.pk:
            raise TeamError("Someone can't lead their own team.")

        if role != target.role:
            before = role_label(target)
            target.role = role
            target.save(update_fields=["role"])
            _platform_event(firm_id, TeamEventKind.ROLE_CHANGED, member=target, **{"from": before, "to": target.get_role_display()})
        if (manager.pk if manager else None) != target.manager_id:
            old = target.manager
            target.manager = manager
            target.save(update_fields=["manager"])
            _platform_event(firm_id, TeamEventKind.MANAGER_CHANGED, member=target, **{"from": label(old), "to": label(manager)})
        if scope_all_clients != target.scope_all_clients:
            target.scope_all_clients = scope_all_clients
            target.save(update_fields=["scope_all_clients"])
            _platform_event(firm_id, TeamEventKind.SCOPE_CHANGED, member=target, to="on" if scope_all_clients else "off")
        if is_active != target.is_active:
            target.is_active = is_active
            target.save(update_fields=["is_active"])
            _platform_event(
                firm_id,
                TeamEventKind.REACTIVATED if is_active else TeamEventKind.DEACTIVATED,
                member=target,
            )
        if make_owner and not target.is_owner:
            target = transfer_ownership(None, target, by_superadmin=PLATFORM_ACTOR)
        return target


def platform_update_firm(firm_id, *, name: str, is_active: bool):
    """Rename a firm, or take it out of service, from outside it."""
    from core.db.session import firm_context
    from core.models import Firm

    name = (name or "").strip()
    if len(name) < 2:
        raise TeamError("Give the firm a name.")
    with firm_context(firm_id), transaction.atomic():
        firm = Firm.objects.select_for_update().filter(pk=firm_id).first()
        if firm is None:
            raise TeamError("That firm no longer exists.")
        if firm.name != name:
            before = firm.name
            firm.name = name
            firm.save(update_fields=["name"])
            TeamEvent.objects.create(
                firm_id=firm.pk,
                kind=TeamEventKind.FIRM_RENAMED,
                actor_id=None,
                detail={"actor": PLATFORM_ACTOR, "from": before, "to": name},
            )
        if firm.is_active != is_active:
            firm.is_active = is_active
            firm.save(update_fields=["is_active"])
        return firm


def platform_remove(membership_id, firm_id) -> None:
    """Take a person out of their firm, so their account is free to join another.

    Removal deletes the membership. Their client assignments go with it; the
    work they did does not, because approvals and classifications point at the
    account, not the membership. Refused for the owner, for the last active
    administrator, and for anyone still leading people or clients.
    """
    from core.db.session import firm_context

    with firm_context(firm_id), transaction.atomic():
        target = (
            FirmMembership.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(firm_id=firm_id, pk=membership_id)
            .first()
        )
        if target is None:
            return
        if target.is_owner:
            raise TeamError("The firm owner can't be removed. Make someone else the owner first.")
        if target.role == Role.FIRM_ADMIN and target.is_active and _active_admins(firm_id) <= 1:
            raise TeamError("The firm needs at least one active firm administrator.")
        if problem := _handover_needed(target):
            raise TeamError(problem)
        _platform_event(firm_id, TeamEventKind.REMOVED, member=target, role=role_label(target))
        target.delete()
