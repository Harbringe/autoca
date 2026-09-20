"""Every account has a profile, from the moment it exists.

A profile page that might not be there is a page every caller has to guard, and
the guard gets forgotten. The row is created with the account by a post-save
signal and removed with it by the cascade, so "does this person have a profile"
is never a question anyone has to ask.
"""

from __future__ import annotations

import pytest

from core.models import Profile, User

pytestmark = pytest.mark.django_db


def test_a_new_account_gets_a_profile():
    user = User.objects.create_user(email="new@example.test", password="x" * 20)
    assert Profile.objects.filter(user=user).exists()


def test_saving_an_account_again_does_not_make_a_second():
    user = User.objects.create_user(email="twice@example.test", password="x" * 20)
    user.full_name = "Changed"
    user.save()
    assert Profile.objects.filter(user=user).count() == 1


def test_deleting_an_account_takes_its_profile_with_it():
    """The cascade, not a second signal, is what keeps this tidy.

    Deleting an account walks its firm-scoped relations to decide what else
    goes, and those cannot be read without a tenant context -- hence the firm
    here, even though this account never joins it.
    """
    from core.db.session import firm_context
    from core.provisioning import create_firm

    firm = create_firm("Somewhere")
    user = User.objects.create_user(email="gone@example.test", password="x" * 20)
    profile_id = user.profile.pk
    with firm_context(firm.pk):
        user.delete()
    assert not Profile.objects.filter(pk=profile_id).exists()


def test_the_name_falls_back_the_way_a_person_would_read_it():
    """Display name, then the account's full name, then the address."""
    user = User.objects.create_user(email="fallback@example.test", password="x" * 20)
    profile = user.profile
    assert profile.name == "fallback@example.test"

    user.full_name = "Arun Nair"
    user.save(update_fields=["full_name"])
    profile.refresh_from_db()
    assert profile.name == "Arun Nair"

    profile.display_name = "CA Arun Nair"
    profile.save(update_fields=["display_name"])
    assert profile.name == "CA Arun Nair"


def test_a_profile_is_not_firm_scoped():
    """It hangs off an account, and an account is resolved before any firm is.

    Making this firm-scoped would reintroduce the chicken-and-egg that keeps the
    user table out of row-level security, and would mean the profile page could
    not open until someone picked a firm.
    """
    from core.models import FirmScopedModel

    assert not issubclass(Profile, FirmScopedModel)
    assert not any(f.name == "firm" for f in Profile._meta.get_fields())
