"""Which clients a member may see, and whose entries they may sign off.

The one statement of the rule. Every view that reaches a client's data goes
through :func:`visible_clients` or :func:`get_visible_client`; the sign-off rule
is checked again inside ``ledger.approval`` and ``classify.proposals`` so it
holds for callers that never pass through a view.

    Firm admin, or scope_all_clients     every client in the firm
    Senior CA                            clients they lead + clients assigned to them
    Staff, Read-only                     clients assigned to them

A client that is not visible is a 404, never a 403: whether a client exists is
itself something a member outside it should not learn.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.http import Http404

from core.models import APPROVER_ROLES, Client, FirmMembership, Role


def sees_all_clients(membership: FirmMembership | None) -> bool:
    if membership is None or not membership.is_active:
        return False
    return membership.role == Role.FIRM_ADMIN or membership.scope_all_clients


def visible_clients(membership: FirmMembership | None) -> QuerySet[Client]:
    if membership is None or not membership.is_active:
        return Client.objects.none()
    clients = Client.objects.filter(firm_id=membership.firm_id)
    if sees_all_clients(membership):
        return clients
    mine = Q(assignments__membership=membership)
    if membership.role == Role.SENIOR_CA:
        mine |= Q(lead=membership)
    return clients.filter(mine).distinct()


def visible_client_ids(membership: FirmMembership | None):
    """A subquery of ids, for filtering tables that reach a client by relation."""
    return visible_clients(membership).values("pk")


def can_see_client(membership: FirmMembership | None, client: Client) -> bool:
    if membership is None or client.firm_id != membership.firm_id:
        return False
    return visible_clients(membership).filter(pk=client.pk).exists()


def get_visible_client(request, client_id) -> Client:
    membership = getattr(request, "membership", None)
    client = visible_clients(membership).filter(pk=client_id).first()
    if client is None:
        raise Http404("No such client.")
    return client


def require_visible(request, client: Client) -> Client:
    """For objects found by their own id: 404 unless their client is visible."""
    if not can_see_client(getattr(request, "membership", None), client):
        raise Http404("Not found.")
    return client


def can_post(membership: FirmMembership | None, client: Client) -> bool:
    """May post and correct this client's entries.

    A firm admin anywhere; otherwise anyone who can see the client, which for a
    CA means the clients they are assigned to. The person keeping the books
    commits their own work -- what a senior does is *sign the books off*
    (``can_sign_off``), a separate and later act that locks them.

    Whether the role may post at all is ``journal.approve``, checked separately;
    this is only "is it their client".
    """
    if membership is None or not membership.is_active or client.firm_id != membership.firm_id:
        return False
    if membership.role == Role.FIRM_ADMIN:
        return True
    return can_see_client(membership, client)


def posting_refusal(client: Client) -> str:
    return f"{client.name} is not one of your assigned clients."


def require_posting_rights(membership: FirmMembership | None, client: Client) -> None:
    from django.core.exceptions import PermissionDenied

    if not can_post(membership, client):
        raise PermissionDenied(posting_refusal(client))


def can_sign_off(membership: FirmMembership | None, client: Client) -> bool:
    """May sign the books off, reopen them, or decide ledger proposals.

    A firm admin anywhere. Otherwise an approver who can see the client and who
    is its lead -- or any approver who can see it, while it has no lead yet.
    """
    if membership is None or not membership.is_active or client.firm_id != membership.firm_id:
        return False
    if membership.role == Role.FIRM_ADMIN:
        return True
    if membership.role not in APPROVER_ROLES or not can_see_client(membership, client):
        return False
    return client.lead_id is None or client.lead_id == membership.pk


def sign_off_refusal(client: Client) -> str:
    return f"Only {client.name}'s lead or a firm administrator can sign off its entries."


def require_sign_off(membership: FirmMembership | None, client: Client) -> None:
    from django.core.exceptions import PermissionDenied

    if not can_sign_off(membership, client):
        raise PermissionDenied(sign_off_refusal(client))
