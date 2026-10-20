"""A few seconds' memory for the figures every screen asks for, and the way a person's own change makes it forget.

A client's page asks, at once, for the firm overview, the firm's alerts and the client's alerts, and each of those used to work everything out
again: the alerts alone build a books-closing report for every client the person may see. Worked out once and shared for ``TTL`` seconds,
the burst of requests that one page makes costs one computation instead of several.

Two things keep it honest:

* **A person's own change is seen at once.** Any successful change made through the API (``core.middleware.freshness``) moves the firm's
  version on, and the version is part of every key, so what was remembered under the old one is never read again. It moves after the change
  is committed, so nothing is remembered that was worked out from before it.
* **What is not a person's change is at most ``TTL`` seconds old.** The assistant's own postings, a statement read by a worker, the date
  changing: the figures catch up within seconds, as they do when a screen refreshes.

Keys carry the firm, so one firm never reads another's; callers add whatever else the result depends on (the person, what they may see).
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache

TTL = 30
#: How long a request waits for another one that is working out the same thing, before it works it out itself.
WAIT_SECONDS = 8.0
_MISSING = object()


def _version_key(firm_id) -> str:
    return f"fresh:v:{firm_id}"


def version(firm_id) -> int:
    return cache.get(_version_key(firm_id), 0)


def bump(firm_id) -> None:
    """Make everything remembered for this firm so far unreadable."""
    key = _version_key(firm_id)
    try:
        cache.incr(key)
    except ValueError:  # not there yet: this bump creates it (at 1), unless another request created it first
        if not cache.add(key, 1, timeout=None):
            try:
                cache.incr(key)
            except ValueError:  # gone again between the two calls: a number nothing was remembered under is a new version too
                cache.set(key, int(time.time()), timeout=None)


def remember(firm_id, name: str, parts, compute, ttl: int | None = None):
    """The result of ``compute()``, shared for ``ttl`` seconds by everyone asking for the same ``name`` and ``parts`` in this firm.

    One request works it out while the others that arrive meanwhile wait for it, so a burst costs one computation. A result is never
    shared across a change (see the module note). ``compute`` raising leaves nothing remembered and lets the next request try.
    ``settings.FRESHNESS_TTL`` is the default for ``ttl``; 0 means nothing is shared.
    """
    ttl = getattr(settings, "FRESHNESS_TTL", TTL) if ttl is None else ttl
    if ttl <= 0:
        return compute()
    key = f"fresh:{firm_id}:{version(firm_id)}:{name}:" + ":".join(str(p) for p in parts)
    found = cache.get(key, _MISSING)
    if found is not _MISSING:
        return found
    lock = key + ":lock"
    if cache.add(lock, 1, timeout=30):
        try:
            value = compute()
            cache.set(key, value, timeout=ttl)
            return value
        finally:
            cache.delete(lock)
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.05)
        found = cache.get(key, _MISSING)
        if found is not _MISSING:
            return found
        if cache.get(lock) is None:  # the other request is gone without leaving a result (it failed): stop waiting for it
            break
    return compute()
