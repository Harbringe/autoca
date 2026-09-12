"""Permission classes, wired to the RBAC map rather than to a second copy of it.

There is exactly one statement anywhere in this codebase about who may do what,
and it is ``core.rbac.PERMISSIONS``. These classes look it up. A view that wants
a permission names the string; it does not re-derive the rule from a role, which
is how two sources of truth start.

Every class here also requires an active firm membership, because the tenant
context comes from the membership -- a request without one cannot read a
firm-scoped table at all, and would otherwise fail deep in PostgreSQL with a
message about ``app.firm_id`` rather than a 403 at the door.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from core.rbac import has_permission


class IsFirmMember(BasePermission):
    """Authenticated, second-factor-verified, and a member of some firm."""

    message = (
        "You are signed in but not an active member of any firm. A firm "
        "administrator has to add you before you can see anything."
    )

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        return getattr(request, "membership", None) is not None


class HasFirmPermission(IsFirmMember):
    """Requires the permission named by the view.

    ``required_permission`` may be a single string or a mapping of HTTP method
    to string, for the common case where reading a collection is open to
    everyone in the firm and writing to it is not.
    """

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False

        required = self._required(request, view)
        if required is None:
            return True

        membership = request.membership
        if has_permission(membership, required):
            return True

        self.message = (
            f"Your role ({membership.get_role_display()}) does not permit "
            f"{required}."
        )
        return False

    @staticmethod
    def _required(request, view) -> str | None:
        required = getattr(view, "required_permission", None)
        if isinstance(required, dict):
            return required.get(request.method)
        return required


class CanApprove(HasFirmPermission):
    """The one that carries real weight.

    Approval is the moment a suggestion becomes a permanent ledger entry, and a
    CA is personally answerable for what is filed. This is checked here *and*
    again inside ``ledger.approval.approve`` -- not redundancy for its own sake,
    but because the second check is the one that holds for callers that never
    pass through a view at all.
    """

    required_permission = "journal.approve"

    @staticmethod
    def _required(request, view) -> str:
        return "journal.approve"
