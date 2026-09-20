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
    "gst.view",
}

#: Keeping the books: uploading, classifying, posting, correcting. The CA who
#: does the work commits it. What is a senior's is *signing the books off*
#: (``books.sign_off``) -- the moment they lock and a senior becomes answerable
#: for them -- and that is deliberately the line, no longer "posting".
_PREPARE = _VIEW | {
    "document.upload",
    #: Taking back a statement uploaded by mistake, and the unsigned entries
    #: posted from it. Signed-off books refuse regardless (``EntryLockedError``).
    "statement.delete",
    "transaction.classify",
    "suggestion.edit",
    "ledger.manage",
    "party.manage",
    "journal.approve",
    "journal.correct",
    #: Saying the books are ready for a senior to look at. Any CA who has
    #: worked them may; deciding is not theirs (``books.sign_off``).
    "books.request",
    #: Uploading the register and GSTR-2B, running the match, resolving rows.
    "gst.prepare",
}

_APPROVE = _PREPARE | {
    "period.close",
    #: Signing the books off, which locks them. The senior's act.
    "books.sign_off",
    #: Signing a GST reconciliation off. Like the books, the senior's act.
    "gst.sign_off",
}

#: Leading a team. Every one of these is limited, for a Senior CA, to their own
#: team and the clients they lead -- that scoping lives in teams.service.
_LEAD = {
    "team.view",
    "team.assign",
    "member.invite",
    "member.deactivate",
}

PERMISSIONS = {
    Role.FIRM_ADMIN: _APPROVE
    | _LEAD
    | {
        "firm.manage",
        "client.update",
        "audit.view",
        "member.manage",
        "member.remove",
        "client.create",
        "client.delete",
    },
    Role.SENIOR_CA: _APPROVE | _LEAD,
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
