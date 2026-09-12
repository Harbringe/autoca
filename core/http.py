"""Small facts about a request that more than one layer needs to agree on.

Three questions, each answered in exactly one place so the middleware, the
views and the audit trail cannot answer them differently:

* which address the request really came from;
* what to call the request in logs;
* whether the caller can read HTML, or needs JSON.
"""

from __future__ import annotations

import re
import uuid

from django.conf import settings

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def client_ip(request) -> str | None:
    """The client's address, trusting exactly as many proxies as are configured.

    ``X-Forwarded-For`` is a header anyone can send. Taking its first entry
    means a caller chooses what address the audit log records for them, which
    defeats the purpose of recording one. The header is only meaningful when a
    known number of trusted proxies have appended to it, in which case the
    client is the entry that many places from the *right*; everything to the
    left of that is whatever the client claimed.

    With ``TRUSTED_PROXY_COUNT`` at zero -- the development default -- the
    header is ignored entirely and the socket address is the answer.
    """
    trusted = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    if trusted > 0:
        forwarded = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",")]
        forwarded = [p for p in forwarded if p]
        if len(forwarded) >= trusted:
            return forwarded[-trusted] or None
    return request.META.get("REMOTE_ADDR") or None


def request_id(request) -> str:
    """The caller's ``X-Request-ID`` if it is a sane token, else a fresh one.

    A client may correlate its logs with ours by sending one. It may not send
    a kilobyte of newlines and control characters to be written verbatim into
    the audit table and every log line.
    """
    supplied = request.headers.get("X-Request-ID", "")
    if supplied and _REQUEST_ID.match(supplied):
        return supplied
    return uuid.uuid4().hex


def wants_json(request) -> bool:
    """True for a caller that cannot make sense of an HTML page.

    Anything under the API prefix is JSON, except the documentation pages a
    person opens in a browser. Elsewhere, a JSON body or an ``Accept`` header
    that asks for JSON and not HTML decides it.
    """
    path = request.path
    if path.startswith(tuple(settings.API_DOC_PATH_PREFIXES)):
        return False
    if path.startswith(tuple(settings.API_PATH_PREFIXES)):
        return True
    if request.content_type == "application/json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept
