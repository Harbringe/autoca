"""A client's profile: registrations kept encrypted and masked from people who may not edit, contacts, notes."""

from __future__ import annotations

import datetime

import pytest

from api.tests.conftest import member, sign_in
from core.db.session import firm_context
from core.models import Client, Role
from core.provisioning import create_client

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
PAN = "ABCDE1234F"
CIN = "U12345MH2020PTC123456"


@pytest.fixture
def url(client_record):
    return f"{V1}/clients/{client_record.pk}/profile/"


def test_a_senior_ca_can_fill_in_the_profile(api, url):
    response = api.patch(
        url,
        {
            "constitution": "PRIVATE_LIMITED",
            "trade_name": "Acme",
            "pan": PAN.lower(),
            "tan": "ABCD12345E",
            "cin": CIN,
            "udyam": "UDYAM-MH-12-1234567",
            "msme_category": "SMALL",
            "contact_name": "  Meera Shah ",
            "contact_email": "meera@example.test",
            "contact2_name": "Raj",
            "client_since": "2021-04-01",
            "notes": "Prefers WhatsApp.",
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["pan"] == PAN
    assert body["cin"] == CIN
    assert body["contact_name"] == "Meera Shah"
    assert body["can_edit"] is True
    assert body["profile_updated_at"]
    assert api.get(url).json()["udyam"] == "UDYAM-MH-12-1234567"


def test_registration_numbers_are_stored_encrypted(api, url, client_record, firm):
    api.patch(url, {"pan": PAN}, format="json")
    with firm_context(firm.pk):
        stored = Client.objects.get(pk=client_record.pk)
        assert PAN.encode() not in bytes(stored.pan_enc)
        assert stored.identifier("pan") == PAN
        assert stored.pan_hash


def test_someone_who_may_not_edit_sees_the_numbers_masked(api, url, firm):
    api.patch(url, {"pan": PAN, "tan": "ABCD12345E"}, format="json")
    reader = sign_in(member(firm, Role.READ_ONLY, "profile-reader@example.test").user)
    body = reader.get(url).json()
    assert body["pan"] == "AB*******F"
    assert body["tan"] == "AB*******E"
    assert body["can_edit"] is False


def test_staff_and_readers_cannot_change_the_profile(staff_api, url, firm):
    assert staff_api.patch(url, {"notes": "x"}, format="json").status_code == 403
    reader = sign_in(member(firm, Role.READ_ONLY, "profile-reader2@example.test").user)
    assert reader.patch(url, {"notes": "x"}, format="json").status_code == 403


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"pan": "NOTAPAN"}, "pan"),
        ({"tan": "123"}, "tan"),
        ({"cin": "12345"}, "cin"),
        ({"udyam": "UDYAM-1"}, "udyam"),
        ({"contact_email": "nope"}, "contact_email"),
        ({"incorporated_on": "2999-01-01"}, "incorporated_on"),
        ({"constitution": "LLP", "cin": CIN}, "cin"),
        ({"constitution": "PRIVATE_LIMITED", "cin": "AAB-1234"}, "cin"),
    ],
)
def test_a_malformed_value_is_refused_with_a_message(api, url, body, field):
    response = api.patch(url, body, format="json")
    assert response.status_code == 400
    assert field in response.json() or field in str(response.json())


def test_an_llp_takes_an_llpin(api, url):
    ok = api.patch(url, {"constitution": "LLP", "cin": "AAB-1234"}, format="json")
    assert ok.status_code == 200, ok.content


def test_an_empty_string_clears_a_field(api, url):
    api.patch(url, {"pan": PAN, "notes": "hello"}, format="json")
    body = api.patch(url, {"pan": "", "notes": ""}, format="json").json()
    assert body["pan"] == "" and body["notes"] == ""


def test_the_same_pan_on_two_clients_is_noticed(api, url, firm):
    other = create_client(firm, "Other Traders", datetime.date(2025, 4, 1))
    api.patch(f"{V1}/clients/{other.pk}/profile/", {"pan": PAN}, format="json")
    body = api.patch(url, {"pan": PAN}, format="json").json()
    assert body["pan_shared_with"] == ["Other Traders"]


def test_the_profile_does_not_change_the_client_name_or_year(api, url, client_record):
    response = api.patch(url, {"name": "Hacked", "fy_start": "2030-01-01"}, format="json")
    assert response.status_code == 200
    assert response.json()["name"] == client_record.name


def test_a_client_in_another_firm_is_not_found(api):
    from core.provisioning import create_firm

    other_firm = create_firm("Somebody Else")
    stranger = create_client(other_firm, "Not Yours", datetime.date(2025, 4, 1))
    assert api.get(f"{V1}/clients/{stranger.pk}/profile/").status_code == 404
    assert api.patch(f"{V1}/clients/{stranger.pk}/profile/", {"notes": "x"}, format="json").status_code == 404
