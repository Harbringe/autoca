"""Stand-in portal for tests and for a server with no provider: any username signs in with OTP ``123456``; the GSTR-2B is empty."""

from __future__ import annotations

import datetime
import json

from .base import GstPortal, PortalError, PortalSession, PortalSessionExpired

STUB_OTP = "123456"


class StubGstPortal(GstPortal):
    def __init__(self, **_ignored):  # settings pass the real provider's options (keys); the stub needs none
        pass

    def request_otp(self, gstin: str, username: str) -> None:
        if not username:
            raise PortalError("Give the portal username.")

    def verify_otp(self, gstin: str, username: str, otp: str) -> PortalSession:
        if str(otp) != STUB_OTP:
            raise PortalError("That OTP is not right.")
        return PortalSession(f"stub:{gstin}", datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=6))

    def refresh(self, token: str) -> PortalSession:
        if not token.startswith("stub:"):
            raise PortalSessionExpired("Sign in to the portal again.")
        return PortalSession(token, datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=6))

    def fetch_gstr2b(self, token: str, year: int, month: int) -> bytes:
        if not token.startswith("stub:"):
            raise PortalSessionExpired("Sign in to the portal again.")
        gstin = token.split(":", 1)[1]
        return json.dumps({"data": {"gstin": gstin, "rtnprd": f"{month:02d}{year}", "docdata": {"b2b": []}}}).encode()
