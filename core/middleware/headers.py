"""Response headers that make the browser enforce what the server intends.

Django's ``SecurityMiddleware`` covers HSTS, nosniff and the referrer policy.
What it does not set is a Content-Security-Policy, and that is the one that
turns a cross-site-scripting bug from a session takeover into a console error.

The policy is strict by default -- scripts and styles from this origin only, no
inline anything, no framing, forms post here and nowhere else -- because the
application shell is built to need nothing more. Two kinds of page cannot live
under that policy and are given their own: the OpenAPI documentation, whose
viewer is loaded from a CDN with inline bootstrap, and the Django admin, which
carries inline scripts of its own. Both are behind the same login as the API,
and the loosened policy still forbids framing and off-origin form posts.

Each response also gets a ``Permissions-Policy`` that switches off the browser
features an accounting application has no use for. A page that can never be
granted the camera cannot be tricked into asking for it.
"""

from __future__ import annotations

from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        policies = settings.CONTENT_SECURITY_POLICIES
        chosen = policies["default"]
        for prefix, policy in policies.get("by_prefix", {}).items():
            if request.path.startswith(prefix):
                chosen = policy
                break
        response.headers.setdefault("Content-Security-Policy", chosen)
        response.headers.setdefault("Permissions-Policy", settings.PERMISSIONS_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response
