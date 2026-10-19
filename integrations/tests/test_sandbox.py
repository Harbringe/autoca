"""The Sandbox adapters against recorded-shape answers (no network, no database): what the provider's published reference says it returns."""

from __future__ import annotations

import json

import pytest

from integrations.gstportal.base import PortalError, PortalNotReady, PortalSessionExpired
from integrations.gstportal.sandbox import SandboxGstPortal
from integrations.gstverify.base import GstinLookupError, GstinNotFound
from integrations.gstverify.sandbox import SandboxGstinVerifier
from integrations.sandbox_client import SandboxClient, SandboxError

GSTIN = "27AAAPL1234C1ZE"


class Fake:
    """Stands in for ``SandboxClient.call``: returns queued answers (or raises them), remembers the calls."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def verifier(*answers):
    v = SandboxGstinVerifier("key_test_x", "secret_test_x")
    v.client.call = Fake(*answers)
    return v


def portal(*answers):
    p = SandboxGstPortal("key_test_x", "secret_test_x")
    p.client.call = Fake(*answers)
    return p


def test_search_gstin_reads_the_portals_fields():
    reply = {"code": 200, "data": {"status_cd": "1", "data": {
        "lgnm": "RAVI TRADERS PRIVATE LIMITED", "tradeNam": "RAVI TRADERS", "sts": "Active", "dty": "Regular", "rgdt": "01/07/2017",
        "pradr": {"addr": {"bno": "12", "bnm": "Heera Plaza", "st": "MG Road", "loc": "Camp", "dst": "Pune", "stcd": "Maharashtra", "pncd": "411001"}},
    }}}
    v = verifier(reply)
    details = v.lookup(GSTIN)
    assert (details.legal_name, details.trade_name, details.status) == ("RAVI TRADERS PRIVATE LIMITED", "RAVI TRADERS", "Active")
    assert details.address == "12, Heera Plaza, MG Road, Camp, Pune" and details.pincode == "411001"
    assert v.client.call.calls[0][1] == "/gst/compliance/public/gstin/search"
    assert v.client.call.calls[0][2]["body"] == {"gstin": GSTIN}


def test_search_gstin_no_record_and_invalid_and_failure():
    with pytest.raises(GstinNotFound):
        verifier({"code": 200, "data": {"status_cd": "0", "error": {"error_cd": "FO8000", "message": "No records found"}}}).lookup(GSTIN)
    with pytest.raises(GstinNotFound):
        verifier(SandboxError("Invalid GSTIN pattern", status=422)).lookup(GSTIN)
    with pytest.raises(GstinLookupError):
        verifier(SandboxError("Could not reach Sandbox (URLError).")).lookup(GSTIN)
    with pytest.raises(GstinLookupError):
        verifier({"code": 200, "data": {"status_cd": "0", "error": {"error_cd": "X", "message": "boom"}}}).lookup(GSTIN)


def test_otp_and_verify_follow_the_reference():
    p = portal({"code": 200, "data": {"status_cd": "1"}},
               {"code": 200, "data": {"status_cd": "1", "access_token": "TOKEN", "session_expiry": 1712947711000}})
    p.request_otp(GSTIN, "user@example.com")
    session = p.verify_otp(GSTIN, "user@example.com", "575757")
    otp_call, verify_call = p.client.call.calls
    assert otp_call[:2] == ("POST", "/gst/compliance/tax-payer/otp") and otp_call[2]["body"] == {"username": "user@example.com", "gstin": GSTIN}
    assert verify_call[1] == "/gst/compliance/tax-payer/otp/verify" and verify_call[2]["params"] == {"otp": 575757}
    assert session.token == "TOKEN" and session.expires_at.year == 2024


def test_a_refused_otp_and_a_dead_session_are_told_apart():
    with pytest.raises(PortalError):
        portal({"code": 200, "data": {"status_cd": "0", "error": {"error_cd": "TEC4001", "message": "OTP server is down"}}}).request_otp(GSTIN, "u")
    with pytest.raises(PortalSessionExpired):
        portal({"code": 200, "data": {"status_cd": "0", "error": {"error_cd": "AUTH4033", "message": "Invalid Session"}}}).refresh("T")
    with pytest.raises(PortalError):
        portal().verify_otp(GSTIN, "u", "12ab")


def test_a_refusal_while_signing_in_is_the_providers_own_words_not_a_dead_session():
    with pytest.raises(PortalError) as refused:
        portal(SandboxError("API access is not enabled for this GSTIN", status=403)).request_otp(GSTIN, "u")
    assert not isinstance(refused.value, PortalSessionExpired) and "API access is not enabled" in str(refused.value)
    with pytest.raises(PortalError) as maxed:
        portal({"code": 200, "data": {"status_cd": "0", "error": {"error_cd": "AUTH403", "message": "Maximum sessions exceeded"}}}).request_otp(GSTIN, "u")
    assert not isinstance(maxed.value, PortalSessionExpired) and "Maximum sessions" in str(maxed.value)
    with pytest.raises(PortalSessionExpired):  # with the taxpayer's own token a 401 does mean the session ended
        portal(SandboxError("Unauthorized", status=401)).refresh("T")


def test_gstr2b_comes_back_in_the_shape_the_upload_reads():
    inner = {"gstin": GSTIN, "rtnprd": "092026", "docdata": {"b2b": [{"ctin": "29ABCPE1234F1ZA", "inv": [{"inum": "INV-1"}]}]}}
    p = portal({"code": 200, "data": {"status_cd": "1", "data": inner}})
    out = json.loads(p.fetch_gstr2b("T", 2026, 9))
    assert out == {"data": inner}
    method, path, kwargs = p.client.call.calls[0]
    assert (method, path, kwargs["token"]) == ("GET", "/gst/compliance/tax-payer/gstrs/gstr-2b/2026/09", "T")


def test_a_split_gstr2b_is_joined_page_by_page(monkeypatch):
    monkeypatch.setattr("integrations.gstportal.sandbox.time.sleep", lambda s: None)
    first = {"gstin": GSTIN, "rtnprd": "092026", "docdata": {"b2b": []}}
    page = lambda ctin: {"code": 200, "data": {"status_cd": "1", "data": {"docdata": {"b2b": [{"ctin": ctin, "inv": []}]}}}}  # noqa: E731
    p = portal({"code": 200, "data": {"status_cd": "3", "fc": 2, "data": first}}, page("A"), page("B"))
    out = json.loads(p.fetch_gstr2b("T", 2026, 9))
    assert [s["ctin"] for s in out["data"]["docdata"]["b2b"]] == ["A", "B"]
    assert [c[2].get("params") for c in p.client.call.calls] == [None, {"file_number": 1}, {"file_number": 2}]


def test_not_generated_yet_is_its_own_error():
    with pytest.raises(PortalNotReady):
        portal({"code": 200, "data": {"status_cd": "0", "error": {"error_cd": "RET2B1023", "message": "GSTR-2B not available"}}}).fetch_gstr2b("T", 2026, 9)


def test_an_unconfigured_client_and_a_non_https_address_do_not_call_out():
    with pytest.raises(SandboxError):
        SandboxClient().call("GET", "/x", token="t")
    with pytest.raises(SandboxError):
        SandboxClient("k", "s", "http://example.test").call("GET", "/x", token="t")


def test_the_label_names_the_environment():
    assert SandboxGstinVerifier("k", "s", "https://api.sandbox.co.in").label == "Sandbox (live)"
    assert SandboxGstinVerifier("k", "s", "https://test-api.sandbox.co.in").label == "Sandbox (test)"
    assert SandboxGstinVerifier("k", "s").label == "Sandbox (test)"
