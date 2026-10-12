"""Refusing a save that would overwrite someone else's change.

A form loads a record, the person edits it for a while, and saves the whole thing. If a colleague saved the same record in
between, the second save silently put the first person's values back. The record carries a short ``version`` (a hash of the
fields a person can edit); the form sends it back as ``expected_version``, and a save whose version no longer matches is
refused with 409 ``stale_edit`` instead of overwriting. No column is needed: the version is computed from the fields.

A form that sends no ``expected_version`` is saved as before, so nothing that does not know about this changes behaviour.
"""

from __future__ import annotations

import hashlib

from django.db import transaction


class StaleEditError(Exception):
    """The record was changed after the form that is saving it was opened."""


def version_of(instance, fields: tuple[str, ...]) -> str:
    joined = "\x1f".join(str(getattr(instance, name, "")) for name in fields)
    return hashlib.sha1(joined.encode()).hexdigest()[:12]  # noqa: S324 - a change marker, not a security hash


class VersionedMixin:
    """For a ModelSerializer: ``version`` on the way out, ``expected_version`` checked on the way in."""

    VERSION_FIELDS: tuple[str, ...] = ()

    def get_version(self, obj) -> str:
        return version_of(obj, self.VERSION_FIELDS)

    def checked_update(self, instance, apply):
        """Run ``apply(instance)`` after confirming, under a row lock, that nobody changed the record since it was opened."""
        expected = (getattr(self, "initial_data", None) or {}).get("expected_version")
        if not expected:
            return apply(instance)
        with transaction.atomic():
            current = type(instance).objects.select_for_update().get(pk=instance.pk)
            if version_of(current, self.VERSION_FIELDS) != expected:
                raise StaleEditError(
                    "Someone else changed this after you opened it. Close it and open it again to see what changed."
                )
            return apply(instance)
