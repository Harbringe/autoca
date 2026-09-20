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


def test_read_only_may_not_post():
    assert not has_permission(membership(Role.READ_ONLY), "journal.approve")
    assert not has_permission(membership(Role.READ_ONLY), "journal.correct")


def test_staff_post_and_correct_but_only_seniors_sign_the_books_off():
    """The CA keeping the books commits their work; the senior signs them off.

    Enforced here, not by hiding a button.
    """
    staff = membership(Role.STAFF)
    assert has_permission(staff, "journal.approve")
    assert has_permission(staff, "journal.correct")
    assert has_permission(staff, "books.request")
    assert not has_permission(staff, "books.sign_off")
    assert not staff.can_approve  # ``can_approve`` is the senior's sign-off role


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
    for permission in ("member.manage", "firm.manage", "client.create"):
        assert has_permission(membership(Role.FIRM_ADMIN), permission)
        assert not has_permission(membership(Role.SENIOR_CA), permission)


def test_a_senior_ca_leads_a_team_and_staff_do_not():
    for permission in ("team.view", "team.assign", "member.invite", "member.deactivate"):
        assert has_permission(membership(Role.SENIOR_CA), permission)
        assert not has_permission(membership(Role.STAFF), permission)
        assert not has_permission(membership(Role.READ_ONLY), permission)


def test_a_deactivated_membership_can_do_nothing():
    """Deactivation is the off switch. It must not depend on the role."""
    for role in Role.values:
        assert not has_permission(membership(role, is_active=False), "client.view")


def test_no_membership_at_all_is_denied():
    assert not has_permission(None, "client.view")


def test_require_permission_raises_rather_than_returning_false():
    """Call sites that forget to check a boolean fail open. This one cannot."""
    with pytest.raises(PermissionDenied, match="books.sign_off"):
        require_permission(membership(Role.STAFF), "books.sign_off")


def test_every_role_appears_in_the_permission_map():
    """A role with no entry silently has no permissions, which reads as a bug."""
    assert set(PERMISSIONS) == set(Role.values)
