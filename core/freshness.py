"""A few seconds' memory for the figures every screen asks for, and the way a person's own change makes it forget.

A client's page asks, at once, for the firm overview, the firm's alerts and the client's alerts, and each of those used to work everything out
again: the alerts alone build a books-closing report for every client the person may see. Worked out once and shared for ``TTL`` seconds,
the burst of requests that one page makes costs one computation instead of several.

Two things keep it honest:

* **A person's own change is seen at once.** Any successful change made through the API (``core.middleware.freshness``) moves the firm's
  version on, and the version is part of every key, so what was remembered under the old one is never read again. It moves after the change
  is committed, so nothing is remembered that was worked out from before it.
* **A change under one client forgets only that client's results.** A write to ``/clients/<id>/...`` moves that client's own version on
  (and the firm-wide one, which the overview and the lists across clients use); results kept for a client (``remember(..., client_id=...)``)
  are keyed on the client's version and on the firm's *structural* version, which only a change that is not under any client (the team,
  a new client) moves. So changing one client of thirty-three costs that client's results being worked out again, not everyone's.
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


def _structural_key(firm_id) -> str:
    return f"fresh:vs:{firm_id}"


def _client_key(firm_id, client_id) -> str:
    return f"fresh:vc:{firm_id}:{client_id}"


def version(firm_id) -> int:
    return cache.get(_version_key(firm_id), 0)


def _move_on(key: str) -> None:
    try:
        cache.incr(key)
    except ValueError:  # not there yet: this creates it (at 1), unless another request created it first
        if not cache.add(key, 1, timeout=None):
            try:
                cache.incr(key)
            except ValueError:  # gone again between the two calls: a number nothing was remembered under is a new version too
                cache.set(key, int(time.time()), timeout=None)


def bump(firm_id, client_id=None) -> None:
    """Make what was remembered unreadable after a change.

    With ``client_id`` (a change under that client): the firm-wide version moves, so overviews and lists across clients are worked out
    again, and that client's own version moves, so its results are; every other client's results stay. Without it (a change that is not
    under one client): the firm-wide version and the structural one move, and nothing remembered for the firm survives.
    """
    _move_on(_version_key(firm_id))
    if client_id is None:
        _move_on(_structural_key(firm_id))
    else:
        _move_on(_client_key(firm_id, client_id))


def remember(firm_id, name: str, parts, compute, ttl: int | None = None, client_id=None):
    """The result of ``compute()``, shared for ``ttl`` seconds by everyone asking for the same ``name`` and ``parts`` in this firm.

    One request works it out while the others that arrive meanwhile wait for it, so a burst costs one computation. A result is never
    shared across a change (see the module note). ``compute`` raising leaves nothing remembered and lets the next request try.
    ``settings.FRESHNESS_TTL`` is the default for ``ttl``; 0 means nothing is shared.

    With ``client_id`` the result belongs to that client: it is forgotten by a change under that client or by a firm-level one, and not by
    a change under another client. Without it the result is forgotten by any change in the firm.
    """
    ttl = getattr(settings, "FRESHNESS_TTL", TTL) if ttl is None else ttl
    if ttl <= 0:
        return compute()
    if client_id is None:
        scope = f"v{version(firm_id)}"
    else:
        scope = f"s{cache.get(_structural_key(firm_id), 0)}c{cache.get(_client_key(firm_id, client_id), 0)}"
    key = f"fresh:{firm_id}:{scope}:{name}:" + ":".join(str(p) for p in parts)
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
