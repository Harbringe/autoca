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

PERMISSIONS = {
    Role.OWNER: {
        "firm.manage",
        "member.invite",
        "member.remove",
        "client.create",
        "client.update",
        "client.delete",
        "client.view",
        "audit.view",
    },
    Role.STAFF: {
        "client.view",
        "client.update",
    },
}


def has_permission(membership, permission: str) -> bool:
    if membership is None or not membership.is_active:
        return False
    return permission in PERMISSIONS.get(membership.role, set())


def require_permission(membership, permission: str) -> None:
    from django.core.exceptions import PermissionDenied

    if not has_permission(membership, permission):
        raise PermissionDenied(f"Your role does not permit {permission}.")
