"""GST reconciliation over HTTP: permissions, isolation, and the whole flow."""

from __future__ import annotations

import io
import json

import pytest

from api.tests.conftest import member, sign_in
from core.identifiers import gstin_check_character
from core.models import Role
from core.provisioning import create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def _g(first):
    return first + gstin_check_character(first)


ME = _g("27AAAPL1234C1Z")
ACME = _g("29ABCPE1234F1Z")

REGISTER = (
    "GSTIN,Invoice No,Date,Taxable Value,CGST,SGST\n"
    f"{ACME},INV-1,12-08-2026,10000,900,900\n"
    f"{ACME},INV-3,25-08-2026,2000,180,180\n"
).encode()

PORTAL = json.dumps(
    {"data": {"gstin": ME, "rtnprd": "082026", "docdata": {"b2b": [{"ctin": ACME, "inv": [
        {"inum": "INV-1", "dt": "12-08-2026", "txval": 10000, "cgst": 900, "sgst": 900}]}]}}}
).encode()


def _file(name, data):
    f = io.BytesIO(data)
    f.name = name
    return {"file": f}


def _start(api, client_record):
    base = f"{V1}/clients/{client_record.pk}/gst"
    reg = api.post(f"{base}/registrations/", {"gstin": ME}, format="json")
    assert reg.status_code == 201, reg.content
    run = api.post(f"{base}/runs/", {"registration": reg.json()["id"], "period": "2026-08"}, format="json")
    assert run.status_code == 201, run.content
    return base, run.json()["id"]


def test_the_whole_flow_over_http(api, client_record):
    base, run = _start(api, client_record)
    assert api.post(f"{base}/runs/{run}/register/", _file("r.csv", REGISTER), format="multipart").status_code == 200
    assert api.post(f"{base}/runs/{run}/portal/", _file("2b.json", PORTAL), format="multipart").status_code == 200
    body = api.post(f"{base}/runs/{run}/reconcile/").json()

    assert body["summary"]["eligible_paise"] == 1800_00
    assert [g["kind"] for g in body["groups"]] == ["missing_in_2b", "matched"]
    assert any("Follow up" in a["text"] for a in body["actions"])

    out = api.get(f"{base}/runs/{run}/export/")
    assert out.status_code == 200 and out.content[:2] == b"PK"  # an xlsx is a zip

    signed = api.post(f"{base}/runs/{run}/sign-off/")
    assert signed.status_code == 200 and signed.json()["status"] == "signed_off"
    frozen = api.post(f"{base}/runs/{run}/reconcile/")
    assert frozen.status_code == 409 and frozen.json()["code"] == "gst_rule"


def test_a_file_that_is_not_2b_is_a_422_with_a_reason(api, client_record):
    base, run = _start(api, client_record)
    r = api.post(f"{base}/runs/{run}/portal/", _file("2b.json", b'{"a": 1}'), format="multipart")
    assert r.status_code == 422 and r.json()["code"] == "gst_file_unreadable"


def test_staff_can_prepare_but_not_sign_off(firm, client_record, staff_api, api):
    base, run = _start(staff_api, client_record)
    staff_api.post(f"{base}/runs/{run}/register/", _file("r.csv", REGISTER), format="multipart")
    staff_api.post(f"{base}/runs/{run}/portal/", _file("2b.json", PORTAL), format="multipart")
    staff_api.post(f"{base}/runs/{run}/reconcile/")
    assert staff_api.post(f"{base}/runs/{run}/sign-off/").status_code == 403


def test_a_reader_can_look_but_not_change(firm, client_record, api):
    _start(api, client_record)
    reader = sign_in(member(firm, Role.READ_ONLY, email="viewer@example.com").user)
    base = f"{V1}/clients/{client_record.pk}/gst"
    assert reader.get(f"{base}/registrations/").status_code == 200
    assert reader.post(f"{base}/registrations/", {"gstin": ACME}, format="json").status_code == 403


def test_another_firms_client_and_runs_are_not_found(api, client_record):
    other = create_firm("Other Firm")
    intruder = sign_in(member(other, Role.SENIOR_CA, email="x@other.example").user)
    base, run = _start(api, client_record)
    assert intruder.get(f"{base}/runs/{run}/").status_code == 404
    assert intruder.get(f"{base}/registrations/").status_code == 404
