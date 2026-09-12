"""Roles, and the one line that matters: who may approve.

A CA carries personal legal responsibility for what is filed, so the boundary
between preparing work and making it permanent is a real professional boundary,
not a UI convenience. It is asserted here against the permission map rather than
against any view, so a new endpoint cannot quietly widen it.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied

from core.models import APPROVER_ROLES, FirmMembership, Role
from core.rbac import PERMISSIONS, has_permission, require_permission


def membership(role, *, is_active: bool = True) -> FirmMembership:
    """An unsaved membership. RBAC is a pure function of role and active flag."""
    return FirmMembership(role=role, is_active=is_active)


@pytest.mark.parametrize("role", sorted(APPROVER_ROLES))
def test_senior_roles_may_approve(role):
    assert has_permission(membership(role), "journal.approve")
    assert membership(role).can_approve


@pytest.mark.parametrize("role", [Role.STAFF, Role.READ_ONLY])
def test_junior_roles_may_not_approve(role):
    """Staff prepare, seniors approve. Enforced here, not by hiding a button."""
    assert not has_permission(membership(role), "journal.approve")
    assert not membership(role).can_approve


def test_staff_can_do_the_work_that_leads_up_to_approval():
    staff = membership(Role.STAFF)

    assert has_permission(staff, "document.upload")
    assert has_permission(staff, "transaction.classify")
    assert has_permission(staff, "suggestion.edit")
    assert staff.can_prepare


def test_read_only_can_look_and_nothing_else():
    reader = membership(Role.READ_ONLY)

    assert has_permission(reader, "journal.view")
    assert not has_permission(reader, "suggestion.edit")
    assert not has_permission(reader, "document.upload")
    assert not reader.can_prepare


def test_only_a_firm_admin_manages_the_firm():
    assert has_permission(membership(Role.FIRM_ADMIN), "member.invite")
    assert not has_permission(membership(Role.SENIOR_CA), "member.invite")


def test_a_deactivated_membership_can_do_nothing():
    """Deactivation is the off switch. It must not depend on the role."""
    for role in Role.values:
        assert not has_permission(membership(role, is_active=False), "client.view")


def test_no_membership_at_all_is_denied():
    assert not has_permission(None, "client.view")


def test_require_permission_raises_rather_than_returning_false():
    """Call sites that forget to check a boolean fail open. This one cannot."""
    with pytest.raises(PermissionDenied, match="journal.approve"):
        require_permission(membership(Role.STAFF), "journal.approve")


def test_every_role_appears_in_the_permission_map():
    """A role with no entry silently has no permissions, which reads as a bug."""
    assert set(PERMISSIONS) == set(Role.values)
