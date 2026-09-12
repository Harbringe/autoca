"""Slowing down whoever is guessing.

A login endpoint with no limit is a password oracle that answers as fast as the
server can hash. This counts failures in the cache under two keys -- the address
the attempt came from, and the account it was aimed at -- and refuses once
either passes its limit for a window. Two keys because each closes a gap the
other leaves: an attacker rotating addresses is still caught on the account,
and one spraying a common password across many accounts is still caught on the
address.

The counter is in the cache rather than the database because it has to be
cheap to touch on every attempt and is worthless the moment the window closes.
Under a single process the in-memory cache is enough; a deployment with more
than one web process points ``CACHE_URL`` at Redis so they share the count,
and ``core.checks`` says so if it is not.

Failures are recorded, successes are not cleared. A correct password following
nine wrong ones from the same address is more likely the tenth guess than a
forgetful owner, and a lockout that a correct guess resets is not a lockout.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("autoca.security")


@dataclass(frozen=True)
class Limit:
    """How many failures in how many seconds, and how long the refusal lasts."""

    attempts: int
    window_seconds: int
    lockout_seconds: int


def _limit(name: str) -> Limit:
    return Limit(**settings.THROTTLE_LIMITS[name])


def _key(scope: str, identity: str) -> str:
    digest = hashlib.sha256(identity.strip().lower().encode()).hexdigest()[:32]
    return f"throttle:{scope}:{digest}"


class Throttled(Exception):
    """The caller has to wait. ``retry_after`` is in seconds."""

    def __init__(self, scope: str, retry_after: int):
        self.scope = scope
        self.retry_after = retry_after
        super().__init__(f"too many attempts ({scope}); retry after {retry_after}s")


def check(scope: str, *identities: str) -> None:
    """Raise :class:`Throttled` if any identity is locked out for ``scope``."""
    limit = _limit(scope)
    for identity in identities:
        if identity and cache.get(_key(f"{scope}:lock", identity)):
            raise Throttled(scope, limit.lockout_seconds)


def record_failure(scope: str, *identities: str) -> None:
    """Count one failure against each identity; lock out any that crossed the line."""
    limit = _limit(scope)
    for identity in identities:
        if not identity:
            continue
        key = _key(f"{scope}:fail", identity)
        # add() is atomic where the backend supports it; incr() on a key that
        # expired between the two calls raises, which is why both are guarded.
        cache.add(key, 0, timeout=limit.window_seconds)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=limit.window_seconds)
            count = 1
        if count >= limit.attempts:
            cache.set(_key(f"{scope}:lock", identity), True, timeout=limit.lockout_seconds)
            logger.warning(
                "lockout scope=%s after %d failures in %ds (identity hashed)",
                scope,
                count,
                limit.window_seconds,
            )


def clear(scope: str, *identities: str) -> None:
    """Forget an identity's failures. For an administrator unlocking an account."""
    for identity in identities:
        if identity:
            cache.delete(_key(f"{scope}:fail", identity))
            cache.delete(_key(f"{scope}:lock", identity))
