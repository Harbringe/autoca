"""Mandatory second factor.

TOTP is not optional for any account. Passing a password gets a session that can
reach exactly the paths in ``settings.MFA_EXEMPT_PATH_PREFIXES`` -- login,
logout, and the MFA enrolment/verification flow -- and nothing else.

Runs BEFORE ``TenantContextMiddleware`` on purpose: a half-authenticated session
should never acquire a tenant context, so an un-verified request cannot reach a
firm-scoped query at all.
"""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect


class MFARequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return self.get_response(request)

        if request.path.startswith(tuple(settings.MFA_EXEMPT_PATH_PREFIXES)):
            return self.get_response(request)

        # is_verified() is installed on the user by django_otp's OTPMiddleware
        # and is True only once a device has been verified this session.
        if not user.is_verified():
            # Enrol if there is no device yet, otherwise challenge.
            target = "/auth/mfa/setup/" if not user.has_mfa else "/auth/mfa/verify/"
            return redirect(f"{target}?next={request.get_full_path()}")

        return self.get_response(request)
