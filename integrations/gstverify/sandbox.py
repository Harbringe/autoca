"""GSTIN lookup through Sandbox's public "search GSTIN" call. Needs only the application token, no taxpayer."""

from __future__ import annotations

from integrations.sandbox_client import SandboxClient, SandboxError

from .base import GstinLookupError, GstinNotFound, GstinVerifier, TaxpayerDetails

NOT_FOUND = "FO8000"


def _address(addr: dict) -> str:
    parts = (addr.get("bno"), addr.get("flno"), addr.get("bnm"), addr.get("st"), addr.get("loc"), addr.get("dst"))
    return ", ".join(str(p).strip() for p in parts if p and str(p).strip())


class SandboxGstinVerifier(GstinVerifier):
    def __init__(self, api_key: str = "", api_secret: str = "", base_url: str = "", timeout: float = 30.0, **_ignored):
        self.client = SandboxClient(api_key, api_secret, base_url, timeout)

    def lookup(self, gstin: str) -> TaxpayerDetails:
        try:
            reply = self.client.call("POST", "/gst/compliance/public/gstin/search", body={"gstin": gstin})
        except SandboxError as exc:
            if exc.status == 422:
                raise GstinNotFound(f"{gstin} is not a valid GSTIN.") from exc
            raise GstinLookupError(str(exc)) from exc
        outer = reply.get("data") or {}
        error = outer.get("error") or {}
        if error.get("error_cd") == NOT_FOUND:
            raise GstinNotFound(f"{gstin} is not on the portal.")
        if str(outer.get("status_cd")) != "1" or not isinstance(outer.get("data"), dict):
            raise GstinLookupError(str(error.get("message") or "The provider gave no details."))
        d = outer["data"]
        addr = (d.get("pradr") or {}).get("addr") or {}
        return TaxpayerDetails(
            gstin=gstin,
            legal_name=str(d.get("lgnm") or ""),
            trade_name=str(d.get("tradeNam") or ""),
            status=str(d.get("sts") or ""),
            registration_type=str(d.get("dty") or ""),
            address=_address(addr),
            state=str(addr.get("stcd") or ""),
            pincode=str(addr.get("pncd") or ""),
            registered_on=str(d.get("rgdt") or ""),
            cancelled_on=str(d.get("cxdt") or ""),
        )
