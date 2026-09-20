"""One profile per account, always.

A profile page that might not exist is a page every caller has to guard, and
the guard gets forgotten. So the row is created with the account and never
deleted separately -- ``Profile.user`` cascades, so removing an account removes
its profile and nothing is orphaned.

``get_or_create`` rather than a bare create: accounts arrive from several paths
(the admin, ``bootstrap_admin``, invite acceptance, the test factories) and some
of them save the same user more than once.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import Profile, User


@receiver(post_save, sender=User, dispatch_uid="core.ensure_profile")
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
