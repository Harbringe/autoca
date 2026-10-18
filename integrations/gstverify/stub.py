"""Stand-in provider for tests and for a server with no provider configured.

Answers from the GSTIN's own characters so the screens can be exercised without a key: a GSTIN whose thirteenth character (the
entity number) is ``9`` reads as cancelled, one with ``8`` is unknown to the portal, and everything else is an active regular registration
named after the embedded PAN. It is plainly marked, so nobody mistakes it for the portal.
"""

from __future__ import annotations

from .base import GstinNotFound, GstinVerifier, TaxpayerDetails

STATES = {"27": "Maharashtra", "24": "Gujarat", "29": "Karnataka", "07": "Delhi", "33": "Tamil Nadu"}


class StubGstinVerifier(GstinVerifier):
    def __init__(self, **_ignored):  # settings pass the real provider's options (keys); the stub needs none
        pass

    def lookup(self, gstin: str) -> TaxpayerDetails:
        gstin = (gstin or "").strip().upper()
        if gstin[12:13] == "8":
            raise GstinNotFound(f"{gstin} is not on the portal.")
        pan = gstin[2:12]
        cancelled = gstin[12:13] == "9"
        return TaxpayerDetails(
            gstin=gstin,
            legal_name=f"STUB LEGAL NAME {pan}",
            trade_name=f"STUB TRADE NAME {pan}",
            status="Cancelled" if cancelled else "Active",
            registration_type="Regular",
            address="Stub address, not from the GST portal",
            state=STATES.get(gstin[:2], gstin[:2]),
            pincode="000000",
            registered_on="2020-01-01",
            cancelled_on="2025-01-01" if cancelled else "",
        )
