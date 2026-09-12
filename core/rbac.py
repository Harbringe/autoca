"""Role-based access control.

One role per firm-user for this phase. The permission map is data rather than
scattered `if role == ...` checks, so that adding a role later is one edit here
instead of an audit of every view.

This layer sits ABOVE tenant isolation and does not replace it. RLS decides
*whose* rows you can see; RBAC decides what you may do with the ones you can.
A bug here is a privilege-escalation inside a firm; a bug in RLS is a breach
across firms. Keep the two concerns separate for exactly that reason.
"""

from core.models import Role

#: What every role can do, however senior. Read access is the floor.
_VIEW = {
    "client.view",
    "document.view",
    "transaction.view",
    "journal.view",
    "report.view",
}

#: Preparing work: uploading, classifying, staging suggestions. Explicitly does
#: not include ``journal.approve`` -- that is the line the whole model exists to
#: draw, since approval is the moment an entry becomes permanent and a CA
#: becomes personally answerable for it.
_PREPARE = _VIEW | {
    "client.update",
    "document.upload",
    "transaction.classify",
    "suggestion.edit",
    "ledger.manage",
    "vendor.manage",
}

_APPROVE = _PREPARE | {
    "journal.approve",
    "journal.correct",
    "period.close",
    "audit.view",
}

PERMISSIONS = {
    Role.FIRM_ADMIN: _APPROVE
    | {
        "firm.manage",
        "member.invite",
        "member.remove",
        "client.create",
        "client.delete",
    },
    Role.SENIOR_CA: _APPROVE,
    Role.STAFF: _PREPARE,
    Role.READ_ONLY: _VIEW,
}


def has_permission(membership, permission: str) -> bool:
    if membership is None or not membership.is_active:
        return False
    return permission in PERMISSIONS.get(membership.role, set())


def require_permission(membership, permission: str) -> None:
    from django.core.exceptions import PermissionDenied

    if not has_permission(membership, permission):
        raise PermissionDenied(f"Your role does not permit {permission}.")
