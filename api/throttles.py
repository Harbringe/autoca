"""A per-person backstop on the requests that cost the most to serve.

Uploads are parsed inside the request and model calls cost money and a provider's daily cap, on a host with a few shared
workers. The limits are generous for real use (a person works through a statement a batch at a time) and exist so one
account, careless or hostile, cannot take the workers or the model budget from everyone else. The count is kept in the
cache, per signed-in person and per scope, so it is as shared as the cache is.
"""

from __future__ import annotations

from rest_framework.exceptions import Throttled
from rest_framework.throttling import SimpleRateThrottle


class _PerPerson(SimpleRateThrottle):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__()

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}


def enforce(request, view, scope: str) -> None:
    """Count this request against the person's allowance for ``scope``; raise a 429 (with when to retry) if it is used up."""
    throttle = _PerPerson(scope)
    if not throttle.allow_request(request, view):
        raise Throttled(wait=throttle.wait())
