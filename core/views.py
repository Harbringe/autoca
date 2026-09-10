"""Authentication and session endpoints.

The frontend is a React SPA on Vercel, so the primary contract here is JSON.
Session cookies (not JWTs) with CSRF enforced: a stolen JWT is valid until it
expires and cannot be revoked, a poor trade for a product holding client
financial records.

The two MFA endpoints additionally render a minimal HTML page for GET / form
POST, so the Django admin is usable in a browser during development. The real,
styled MFA screens belong to the SPA; these are the bare minimum to not leave a
browser session stranded at a JSON blob.
"""

from __future__ import annotations

import base64
import io
import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


def _wants_json(request) -> bool:
    """True for SPA/API callers, False for a browser rendering HTML."""
    if request.content_type == "application/json":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _safe_next(request, default: str = "/admin/") -> str:
    """Post-MFA redirect target, guarded against open-redirect."""
    nxt = request.POST.get("next") or request.GET.get("next") or default
    if url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return default


def _qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=9, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_GET
def healthz(request):
    """Liveness only. Touches no database and no tenant context.

    Render's free tier spins down after 15 minutes idle and takes 30-60s to
    wake; ping this before a demo.
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


def _confirm_and_login(request, device) -> None:
    if not device.confirmed:
        device.confirmed = True
        device.save(update_fields=["confirmed"])
    otp_login(request, device)


@require_http_methods(["GET", "POST"])
def mfa_setup(request):
    """Enrol a TOTP device.

    JSON POST (SPA): (re)provision an unconfirmed device, return its otpauth URI.
    GET (browser):   render the QR + setup key + a code field.
    Form POST:       verify the code, confirm the device, sign the second factor
                     in, and redirect on.

    The device stays unconfirmed -- and unusable -- until a generated code is
    proven, so a mistyped secret cannot lock an account out.
    """
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.get_full_path()}")

    if _wants_json(request) and request.method == "POST":
        TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
        device = TOTPDevice.objects.create(user=request.user, name="default", confirmed=False)
        return JsonResponse({"provisioningUri": device.config_url})

    has_confirmed = TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
    if has_confirmed:
        # Already enrolled -- the challenge page is the right place.
        return redirect(f"/auth/mfa/verify/?next={_safe_next(request)}")

    device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=request.user, name="default", confirmed=False)

    error = None
    if request.method == "POST":
        if device.verify_token(request.POST.get("token", "").strip()):
            _confirm_and_login(request, device)
            return redirect(_safe_next(request))
        error = "That code didn't match. Enter the current one from your app."

    return render(
        request,
        "mfa_setup.html",
        {
            "email": request.user.email,
            "issuer": settings.OTP_TOTP_ISSUER,
            "secret": base64.b32encode(device.bin_key).decode(),
            "qr_svg": _qr_svg(device.config_url),
            "next": _safe_next(request),
            "error": error,
        },
    )


@require_http_methods(["GET", "POST"])
def mfa_verify(request):
    """Challenge an already-enrolled TOTP device.

    JSON POST (SPA) keeps the original contract; GET / form POST render and
    process the browser page.
    """
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.get_full_path()}")

    device = (
        TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        or TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
    )

    if _wants_json(request) and request.method == "POST":
        token = str(_body(request).get("token", "")).strip()
        if device is None:
            return JsonResponse({"detail": "No TOTP device enrolled."}, status=400)
        if not device.verify_token(token):
            return JsonResponse({"detail": "Invalid code."}, status=401)
        _confirm_and_login(request, device)
        return JsonResponse({"detail": "Verified."})

    if device is None:
        return redirect(f"/auth/mfa/setup/?next={_safe_next(request)}")

    error = None
    if request.method == "POST":
        if device.verify_token(request.POST.get("token", "").strip()):
            _confirm_and_login(request, device)
            return redirect(_safe_next(request))
        error = "That code didn't match. Enter the current one from your app."

    return render(
        request,
        "mfa_verify.html",
        {"email": request.user.email, "next": _safe_next(request), "error": error},
    )


@require_GET
def me(request):
    """Who am I, and which firm am I acting for.

    Reads ``request.firm`` / ``request.membership`` set by
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
