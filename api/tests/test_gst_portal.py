"""Signing a GSTIN in to the GST portal and fetching GSTR-2B from it (stub provider): the flow, the limits, and what is kept."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from api.tests.conftest import member, sign_in
from core.identifiers import gstin_check_character
from core.models import Role
from core.provisioning import create_firm
from gst.models import GstRegistration, ReconRun, RunStatus
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _g(first):
    return first + gstin_check_character(first)


ME = _g("27AAAPL1234C1Z")
OTP = "123456"


@pytest.fixture(autouse=True)
def _stub(settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "gstportal": "integrations.gstportal.stub.StubGstPortal"}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def _setup(api, client_record):
    base = f"/api/v1/clients/{client_record.pk}/gst"
    reg = api.post(f"{base}/registrations/", {"gstin": ME}, format="json").json()
    run = api.post(f"{base}/runs/", {"registration": reg["id"], "period": "2026-08"}, format="json").json()
    return base, reg["id"], run["id"]


def _connect(api, base, reg):
    assert api.post(f"{base}/registrations/{reg}/portal/otp/", {"username": "owner@example.com"}, format="json").status_code == 204
    return api.post(f"{base}/registrations/{reg}/portal/verify/", {"username": "owner@example.com", "otp": OTP}, format="json")


def test_connect_then_fetch_loads_gstr2b_like_an_upload(api, client_record):
    base, reg, run = _setup(api, client_record)
    assert api.get(f"{base}/registrations/").json()["results"][0]["portal_connected"] is False

    connected = _connect(api, base, reg)
    assert connected.status_code == 200
    body = connected.json()
    assert body["portal_connected"] is True and body["portal_username"] == "owner@example.com"

    fetched = api.post(f"{base}/runs/{run}/portal-fetch/")
    assert fetched.status_code == 200, fetched.content
    assert fetched.json()["run"]["has_portal"] is True


def test_the_session_is_kept_encrypted_and_the_otp_is_not_kept(api, client_record):
    base, reg, _run = _setup(api, client_record)
    _connect(api, base, reg)
    row = GstRegistration.objects.get(pk=reg)
    assert b"stub:" not in bytes(row.portal_session_enc) and b"owner@example.com" not in bytes(row.portal_username_enc)
    assert OTP not in repr(row.__dict__)


def test_a_wrong_otp_is_refused_and_connects_nothing(api, client_record):
    base, reg, _run = _setup(api, client_record)
    api.post(f"{base}/registrations/{reg}/portal/otp/", {"username": "owner@example.com"}, format="json")
    bad = api.post(f"{base}/registrations/{reg}/portal/verify/", {"username": "owner@example.com", "otp": "000000"}, format="json")
    assert bad.status_code == 409 and bad.json()["code"] == "gst_rule"
    assert GstRegistration.objects.get(pk=reg).portal_session_enc is None


def test_fetching_before_connecting_says_to_connect(api, client_record):
    base, _reg, run = _setup(api, client_record)
    response = api.post(f"{base}/runs/{run}/portal-fetch/")
    assert response.status_code == 409 and "Connect" in response.json()["detail"]


def test_an_ended_session_asks_for_a_new_otp(api, client_record):
    base, reg, run = _setup(api, client_record)
    _connect(api, base, reg)
    GstRegistration.objects.filter(pk=reg).update(portal_session_expires=timezone.now() - datetime.timedelta(minutes=1))
    response = api.post(f"{base}/runs/{run}/portal-fetch/")
    assert response.status_code == 409 and "Connect" in response.json()["detail"]


def test_a_session_near_its_end_is_renewed_before_use(api, client_record):
    base, reg, run = _setup(api, client_record)
    _connect(api, base, reg)
    GstRegistration.objects.filter(pk=reg).update(portal_session_expires=timezone.now() + datetime.timedelta(minutes=5))
    assert api.post(f"{base}/runs/{run}/portal-fetch/").status_code == 200
    assert GstRegistration.objects.get(pk=reg).portal_session_expires > timezone.now() + datetime.timedelta(hours=1)


def test_disconnect_forgets_the_session(api, client_record):
    base, reg, run = _setup(api, client_record)
    _connect(api, base, reg)
    assert api.delete(f"{base}/registrations/{reg}/portal/").status_code == 204
    row = GstRegistration.objects.get(pk=reg)
    assert row.portal_session_enc is None and row.portal_username_enc is None
    assert api.post(f"{base}/runs/{run}/portal-fetch/").status_code == 409


def test_a_signed_off_run_is_not_fetched_into(api, client_record):
    base, reg, run = _setup(api, client_record)
    _connect(api, base, reg)
    ReconRun.objects.filter(pk=run).update(status=RunStatus.SIGNED_OFF)
    again = api.post(f"{base}/runs/{run}/portal-fetch/")
    assert again.status_code == 409 and "signed off" in again.json()["detail"]


def test_another_firm_cannot_connect_a_registration_it_cannot_see(api, client_record):
    base, reg, _run = _setup(api, client_record)
    stranger = sign_in(member(create_firm("Other Firm"), Role.FIRM_ADMIN, email="x@other.example").user)
    assert stranger.post(f"{base}/registrations/{reg}/portal/otp/", {"username": "u"}, format="json").status_code == 404
