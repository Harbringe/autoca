"""The GST portal through Sandbox (sandbox.co.in). Endpoints are from Sandbox's published API reference.

Two details the reference leaves open are handled defensively and are the first things to confirm on a real call in the test
environment: the month's format in the GSTR-2B path (sent as two digits) and where the page count sits when a return is split into
files (looked for as ``fc`` in the payload, else the single page is used).
"""

from __future__ import annotations

import datetime
import json
import time

from integrations.sandbox_client import SandboxClient, SandboxError

from .base import GstPortal, PortalError, PortalNotReady, PortalSession, PortalSessionExpired

NOT_READY = {"RET2B1023", "RET2B1016"}
SESSION_ERRORS = {"AUTH4033", "AUTH403"}


def _expiry(data: dict) -> datetime.datetime:
    millis = data.get("session_expiry") or data.get("token_expiry")
    if millis:
        return datetime.datetime.fromtimestamp(int(millis) / 1000, datetime.UTC)
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5)


def _check(reply: dict, *, signing_in: bool = False) -> dict:
    """The inner ``data`` of an answer, or the right error. Failures often arrive as HTTP 200 with ``status_cd`` 0.

    While signing in there is no session to have ended, so a session-style code is the provider's own refusal and is shown as it is."""
    outer = reply.get("data") or {}
    error = outer.get("error") or {}
    code = error.get("error_cd")
    if code in NOT_READY:
        raise PortalNotReady(str(error.get("message") or "The portal has no GSTR-2B for that month yet."))
    if code in SESSION_ERRORS and not signing_in:
        raise PortalSessionExpired("The portal session has ended. Sign in again with a new OTP.")
    if str(outer.get("status_cd", "1")) == "0" or error:
        raise PortalError(str(error.get("message") or "The portal refused the request."))
    return outer


class SandboxGstPortal(GstPortal):
    def __init__(self, api_key: str = "", api_secret: str = "", base_url: str = "", timeout: float = 60.0, **_ignored):
        self.client = SandboxClient(api_key, api_secret, base_url, timeout)

    def _call(self, *args, **kwargs) -> dict:
        try:
            return self.client.call(*args, **kwargs)
        except SandboxError as exc:
            # Only a call made with the taxpayer's own token can find that session ended; for the application's calls a
            # 401 or 403 is the provider refusing us, and its own words are what a person needs.
            if exc.status in (401, 403) and kwargs.get("token"):
                raise PortalSessionExpired("The portal session has ended. Sign in again with a new OTP.") from exc
            detail = f" (HTTP {exc.status})" if exc.status else ""
            raise PortalError(f"{exc}{detail}") from exc

    def request_otp(self, gstin: str, username: str) -> None:
        _check(self._call("POST", "/gst/compliance/tax-payer/otp", body={"username": username, "gstin": gstin}), signing_in=True)

    def verify_otp(self, gstin: str, username: str, otp: str) -> PortalSession:
        if not str(otp).isdigit():
            raise PortalError("The OTP is digits only.")
        reply = self._call("POST", "/gst/compliance/tax-payer/otp/verify", params={"otp": int(otp)}, body={"username": username, "gstin": gstin})
        data = _check(reply, signing_in=True)
        if not data.get("access_token"):
            raise PortalError("The portal did not start a session.")
        return PortalSession(data["access_token"], _expiry(data))

    def refresh(self, token: str) -> PortalSession:
        data = _check(self._call("POST", "/gst/compliance/tax-payer/session/refresh", token=token))
        if not data.get("access_token"):
            raise PortalSessionExpired("The portal session could not be extended. Sign in again.")
        return PortalSession(data["access_token"], _expiry(data))

    def fetch_gstr2b(self, token: str, year: int, month: int) -> bytes:
        path = f"/gst/compliance/tax-payer/gstrs/gstr-2b/{year}/{month:02d}"
        first = _check(self._call("GET", path, token=token))
        body = dict(first.get("data") or {})
        if str(first.get("status_cd")) == "3":
            pages = int(first.get("fc") or body.get("fc") or 1)
            for number in range(1, pages + 1):
                time.sleep(0.2)
                more = _check(self._call("GET", path, token=token, params={"file_number": number}))
                _merge(body, more.get("data") or {})
        return json.dumps({"data": body}).encode()


def _merge(into: dict, page: dict) -> None:
    """Add a later page's invoice sections to the first page's, section by section."""
    target = into.setdefault("docdata", {})
    for section, suppliers in (page.get("docdata") or {}).items():
        if isinstance(suppliers, list):
            target.setdefault(section, []).extend(suppliers)
