"""Creating a firm and its first user.

This is the one flow that has to bootstrap a tenant context out of nothing, and
it is worth understanding why it looks the way it does.

``core_firm``'s policy is ``id = app.current_firm_id()`` with a matching WITH
CHECK. So you cannot insert a firm row without already having that firm's id in
the tenant context. That sounds circular, and is not: the id is a client-side
UUID, so we mint it, enter its context, and insert. The insert then satisfies
WITH CHECK by construction.

The alternative -- an RLS exemption for firm creation -- would mean a hole in the
policy that exists for one legitimate caller and is available to every other one.
This way there is no hole.
"""

from __future__ import annotations

import uuid

from django.db import transaction

from core.db.session import firm_context
from core.models import Client, Firm, FirmMembership, Role, User


@transaction.atomic
def create_firm(name: str, firm_id=None) -> Firm:
    """Create a firm inside its own freshly-minted tenant context."""
    firm_id = firm_id or uuid.uuid4()
    with firm_context(firm_id):
        return Firm.objects.create(id=firm_id, name=name)


def create_user(email: str, password: str, full_name: str = "") -> User:
    """Create a person. Not firm-scoped, so no tenant context is involved."""
    return User.objects.create_user(email=email, password=password, full_name=full_name)


def add_member(firm, user, role=Role.STAFF) -> FirmMembership:
    """Attach a user to a firm. Requires that firm's context."""
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


def create_client(firm, name: str, fy_start) -> Client:
    with firm_context(firm.pk):
        return Client.objects.create(firm=firm, name=name, fy_start=fy_start)
