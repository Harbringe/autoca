"""The browser MFA flow: HTML enrolment + form POST, JSON contract preserved."""

from __future__ import annotations

import pytest
from django.test import Client as HttpClient
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.provisioning import add_member, create_firm, create_user

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


def _code(device: TOTPDevice, offset: int = 0) -> str:
    return f"{totp(device.bin_key, device.step, device.t0, device.digits, offset):0{device.digits}d}"


@pytest.fixture
def member(db):
    firm = create_firm("Acme")
    user = create_user("member@example.com", PASSWORD)
    add_member(firm, user)
    return user


def _login(http: HttpClient) -> None:
    http.post(
        "/auth/login/",
        {"email": "member@example.com", "password": PASSWORD},
        content_type="application/json",
    )


def test_setup_page_renders_with_qr_and_key(member):
    http = HttpClient()
    _login(http)

    resp = http.get("/auth/mfa/setup/?next=/admin/")

    assert resp.status_code == 200
    html = resp.content.decode()
    assert "<svg" in html  # QR
    assert 'name="token"' in html
    assert TOTPDevice.objects.filter(user=member, confirmed=False).count() == 1


def test_setup_form_post_confirms_device_and_redirects(member):
    http = HttpClient()
    _login(http)
    http.get("/auth/mfa/setup/")  # provisions the unconfirmed device
    device = TOTPDevice.objects.get(user=member)

    resp = http.post("/auth/mfa/setup/?next=/admin/", {"token": _code(device)})

    assert resp.status_code == 302
    assert resp["Location"] == "/admin/"
    device.refresh_from_db()
    assert device.confirmed is True
    # session now carries a verified second factor
    assert http.get("/api/me/").status_code == 200


def test_setup_form_post_rejects_a_bad_code(member):
    http = HttpClient()
    _login(http)
    http.get("/auth/mfa/setup/")

    resp = http.post("/auth/mfa/setup/", {"token": "000000"})

    assert resp.status_code == 200
    assert "didn&#x27;t match" in resp.content.decode() or "didn't match" in resp.content.decode()
    assert not TOTPDevice.objects.get(user=member).confirmed


def test_verify_page_challenges_an_enrolled_device(member):
    device = TOTPDevice.objects.create(user=member, name="default", confirmed=True)
    http = HttpClient()
    _login(http)

    assert http.get("/auth/mfa/verify/").status_code == 200

    resp = http.post("/auth/mfa/verify/?next=/admin/", {"token": _code(device)})
    assert resp.status_code == 302
    assert resp["Location"] == "/admin/"
    assert http.get("/api/me/").status_code == 200


def test_setup_get_redirects_to_verify_when_already_enrolled(member):
    TOTPDevice.objects.create(user=member, name="default", confirmed=True)
    http = HttpClient()
    _login(http)

    resp = http.get("/auth/mfa/setup/?next=/admin/")
    assert resp.status_code == 302
    assert "/auth/mfa/verify/" in resp["Location"]


def test_verify_get_redirects_to_setup_when_no_device(member):
    http = HttpClient()
    _login(http)

    resp = http.get("/auth/mfa/verify/")
    assert resp.status_code == 302
    assert "/auth/mfa/setup/" in resp["Location"]


def test_json_contract_still_works_for_the_spa(member):
    http = HttpClient()
    _login(http)

    provision = http.post(
        "/auth/mfa/setup/", content_type="application/json", data="{}"
    )
    assert provision.status_code == 200
    assert provision.json()["provisioningUri"].startswith("otpauth://")

    device = TOTPDevice.objects.get(user=member)
    verified = http.post(
        "/auth/mfa/verify/",
        {"token": _code(device)},
        content_type="application/json",
    )
    assert verified.status_code == 200
    assert verified.json()["detail"] == "Verified."


def test_open_redirect_is_refused(member):
    http = HttpClient()
    _login(http)
    http.get("/auth/mfa/setup/")
    device = TOTPDevice.objects.get(user=member)

    resp = http.post("/auth/mfa/setup/?next=https://evil.example/", {"token": _code(device)})
    assert resp.status_code == 302
    assert resp["Location"] == "/admin/"  # fell back to the safe default


def test_unauthenticated_hitting_mfa_pages_is_sent_to_login():
    resp = HttpClient().get("/auth/mfa/setup/")
    assert resp.status_code == 302
    assert "/auth/login/" in resp["Location"]
