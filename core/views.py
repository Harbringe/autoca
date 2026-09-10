"""Authentication and session endpoints.

JSON rather than server-rendered forms, because the frontend is a React SPA on
Vercel. Session cookies (not JWTs) with CSRF enforced: a stolen JWT is valid
until it expires and cannot be revoked, which is a poor trade for a product
holding client financial records.

Scope note: these are the endpoints the MFA middleware needs in order to have
somewhere to redirect to, plus enough of a session to exercise the tenancy
middleware end to end. No feature endpoints live here.
"""

from __future__ import annotations

import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_GET
def healthz(request):
    """Liveness only. Deliberately touches no database and no tenant context.

    Render's free tier spins down after 15 minutes idle and takes 30-60s to wake;
    this is the endpoint to ping before a demo.
    """
    return JsonResponse({"status": "ok"})


@require_POST
def login_view(request):
    data = _body(request)
    user = authenticate(
        request, username=data.get("email", ""), password=data.get("password", "")
    )
    if user is None:
        # One message for both wrong-email and wrong-password. Distinguishing
        # them turns this endpoint into a user-enumeration oracle.
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    login(request, user)
    return JsonResponse(
        {
            "detail": "Password accepted. A second factor is required.",
            "mfa": "verify" if user.has_mfa else "setup",
        }
    )


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"detail": "Signed out."})


@require_POST
def mfa_setup(request):
    """Provision an unconfirmed TOTP device and return its enrolment URI.

    The device stays unconfirmed -- and so unusable -- until the user proves they
    can generate a code from it. Confirming on creation would let a
    mis-transcribed secret lock the account out permanently.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Sign in first."}, status=401)

    TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
    device = TOTPDevice.objects.create(user=request.user, name="default", confirmed=False)
    return JsonResponse({"provisioningUri": device.config_url})


@require_POST
def mfa_verify(request):
    """Verify a TOTP code, confirming the device on first successful use."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Sign in first."}, status=401)

    token = str(_body(request).get("token", "")).strip()
    device = (
        TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        or TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
    )
    if device is None:
        return JsonResponse({"detail": "No TOTP device enrolled."}, status=400)

    if not device.verify_token(token):
        return JsonResponse({"detail": "Invalid code."}, status=401)

    if not device.confirmed:
        device.confirmed = True
        device.save(update_fields=["confirmed"])

    otp_login(request, device)
    return JsonResponse({"detail": "Verified."})


@require_GET
def me(request):
    """Who am I, and which firm am I acting for.

    Reads ``request.firm`` and ``request.membership``, both set by
    TenantContextMiddleware, so it doubles as a live check that the tenancy
    chain is wired correctly.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not signed in."}, status=401)

    membership = getattr(request, "membership", None)
    firm = getattr(request, "firm", None)
    return JsonResponse(
        {
            "email": request.user.email,
            "fullName": request.user.full_name,
            "firm": {"id": str(firm.pk), "name": firm.name} if firm else None,
            "role": membership.role if membership else None,
        }
    )
