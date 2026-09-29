"""Authentication and session endpoints.

The web application is a separate static deployment, so the primary contract here is JSON.
Session cookies (not JWTs) with CSRF enforced: a stolen JWT is valid until it
expires and cannot be revoked, a poor trade for a product holding client
financial records.

The two MFA endpoints additionally render a minimal HTML page for GET / form
POST, so the Django admin is usable in a browser during development. The real,
styled MFA screens belong to the web application; these are the bare minimum to not leave a
browser session stranded at a JSON blob.
"""

from __future__ import annotations

import base64
import io
import json
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from core import throttle
from core.http import client_ip
from core.http import wants_json as _wants_json
from core.middleware.mfa import mfa_disabled

security_log = logging.getLogger("autoca.security")


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


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
def to_frontend(request):
    return redirect(settings.FRONTEND_URL)


@require_GET
def healthz(request):
    """Liveness only. Touches no database and no tenant context.

    Render's free tier spins down after 15 minutes idle and takes 30-60s to
    wake; ping this before a demo.
    """
    return JsonResponse({"status": "ok"})


def _throttled(exc: throttle.Throttled) -> JsonResponse:
    response = JsonResponse(
        {
            "code": "too_many_attempts",
            "detail": f"Too many attempts. Try again in {max(exc.retry_after // 60, 1)} minutes.",
        },
        status=429,
    )
    response["Retry-After"] = str(exc.retry_after)
    return response


@require_POST
def login_view(request):
    data = _body(request)
    email = str(data.get("email", ""))[:254].strip().lower()
    address = client_ip(request) or ""

    # Refuse before hashing anything, so a locked-out caller costs nothing.
    try:
        throttle.check("login", email)
    except throttle.Throttled as exc:
        security_log.warning("login refused (locked out) ip=%s", address)
        return _throttled(exc)

    user = authenticate(request, username=email, password=str(data.get("password", "")))
    if user is None:
        # One message for both wrong-email and wrong-password. Distinguishing
        # them turns this endpoint into a user-enumeration oracle.
        throttle.record_failure("login", email)
        security_log.info("login failed ip=%s", address)
        return JsonResponse(
            {"code": "invalid_credentials", "detail": "Invalid credentials."}, status=401
        )

    login(request, user)
    user.last_login_ip = address or None
    user.save(update_fields=["last_login_ip"])
    security_log.info("login password accepted user=%s ip=%s", user.pk, address)
    if mfa_disabled():
        security_log.warning("MFA_DISABLED is on: user=%s signed in without a second factor", user.pk)
        return JsonResponse({"detail": "Signed in. Second factor disabled locally.", "mfa": None})
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

    # The page and the browser's favicon request are both sent here on a first visit. Locking the
    # user row makes the second wait for the first, so only one device is ever created and the QR
    # shown is the one the code is checked against.
    with transaction.atomic():
        get_user_model().objects.select_for_update().filter(pk=request.user.pk).first()
        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).order_by("id").first()
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

    # A code can be used once, so a form submitted twice (a double click, a browser resend) fails
    # the second time. The first already passed; show where it led, not an error.
    if request.user.is_verified():
        if _wants_json(request) and request.method == "POST":
            return JsonResponse({"detail": "Verified."})
        return redirect(_safe_next(request))

    device = (
        TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
        or TOTPDevice.objects.filter(user=request.user, confirmed=False).order_by("id").first()
    )

    if _wants_json(request) and request.method == "POST":
        address = client_ip(request) or ""
        try:
            throttle.check("mfa", address, str(request.user.pk))
        except throttle.Throttled as exc:
            security_log.warning("mfa refused (locked out) user=%s ip=%s", request.user.pk, address)
            return _throttled(exc)
        token = str(_body(request).get("token", "")).strip()
        if device is None:
            return JsonResponse(
                {"code": "mfa_not_enrolled", "detail": "No TOTP device enrolled."}, status=400
            )
        if not device.verify_token(token):
            throttle.record_failure("mfa", address, str(request.user.pk))
            security_log.info("mfa failed user=%s ip=%s", request.user.pk, address)
            return JsonResponse({"code": "invalid_code", "detail": "Invalid code."}, status=401)
        _confirm_and_login(request, device)
        security_log.info("mfa verified user=%s ip=%s", request.user.pk, address)
        return JsonResponse({"detail": "Verified."})

    if device is None:
        return redirect(f"/auth/mfa/setup/?next={_safe_next(request)}")

    error = None
    if request.method == "POST":
        address = client_ip(request) or ""
        try:
            throttle.check("mfa", address, str(request.user.pk))
        except throttle.Throttled as exc:
            error = f"Too many attempts. Try again in {max(exc.retry_after // 60, 1)} minutes."
        else:
            if device.verify_token(request.POST.get("token", "").strip()):
                _confirm_and_login(request, device)
                return redirect(_safe_next(request))
            throttle.record_failure("mfa", address, str(request.user.pk))
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
