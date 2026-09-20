"""Mandatory second factor.

TOTP is not optional for any account. Passing a password gets a session that can
reach exactly the paths in ``settings.MFA_EXEMPT_PATH_PREFIXES`` -- login,
logout, and the MFA enrolment/verification flow -- and nothing else.

Runs BEFORE ``TenantContextMiddleware`` on purpose: a half-authenticated session
should never acquire a tenant context, so an un-verified request cannot reach a
firm-scoped query at all.

A browser is redirected to the enrolment or challenge page. An API caller gets a
403 with a code instead: a 302 to an HTML page is unreadable to a ``fetch()``,
and an HTTP client that follows redirects by default would report it as a
success.
"""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

from core.http import wants_json as _wants_json


def mfa_disabled() -> bool:
    """The local-demo switch. Never true outside DEBUG, whatever the setting says."""
    return bool(settings.DEBUG and getattr(settings, "MFA_DISABLED", False))


class MFARequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated or mfa_disabled():
            return self.get_response(request)

        if request.path.startswith(tuple(settings.MFA_EXEMPT_PATH_PREFIXES)):
            return self.get_response(request)

        # is_verified() is installed on the user by django_otp's OTPMiddleware
        # and is True only once a device has been verified this session.
        if not user.is_verified():
            # Enrol if there is no device yet, otherwise challenge.
            enrolled = user.has_mfa
            target = "/auth/mfa/verify/" if enrolled else "/auth/mfa/setup/"

            # An API caller gets an answer, not a redirect. A 302 to an HTML
            # enrolment page is unreadable to a fetch() and, worse, looks like a
            # success to anything that follows redirects by default.
            if _wants_json(request):
                return JsonResponse(
                    {
                        "code": "mfa_required" if enrolled else "mfa_enrolment_required",
                        "detail": (
                            "This session has not passed its second factor."
                            if enrolled
                            else "This account has no second factor enrolled yet."
                        ),
                        "verify_at": target,
                    },
                    status=403,
                )

            return redirect(f"{target}?next={request.get_full_path()}")

        return self.get_response(request)
