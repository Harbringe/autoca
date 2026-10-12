"""A form that saves a party or a ledger after a colleague changed it is refused, not allowed to overwrite them."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


@pytest.fixture
def party(api, client_record):
    response = api.post(f"{V1}/clients/{client_record.pk}/parties/", {"canonical_name": "Shree Traders", "role": "VENDOR"}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


@pytest.fixture
def ledger(api, client_record):
    response = api.post(f"{V1}/clients/{client_record.pk}/ledgers/", {"name": "Printing", "group": "INDIRECT_EXPENSE"}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def test_a_party_save_with_the_current_version_goes_through(api, client_record, party):
    url = f"{V1}/clients/{client_record.pk}/parties/{party['id']}/"
    response = api.patch(url, {"canonical_name": "Shree Traders Ltd", "expected_version": party["version"]}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["canonical_name"] == "Shree Traders Ltd"
    assert response.json()["version"] != party["version"]


def test_a_party_save_with_a_stale_version_is_refused_and_changes_nothing(api, client_record, party):
    url = f"{V1}/clients/{client_record.pk}/parties/{party['id']}/"
    # A colleague saves first.
    assert api.patch(url, {"tds_section": "194C", "expected_version": party["version"]}, format="json").status_code == 200
    # The second person's form was opened before that, so its version is old.
    late = api.patch(url, {"canonical_name": "Renamed late", "expected_version": party["version"]}, format="json")
    assert late.status_code == 409
    assert late.json()["code"] == "stale_edit"
    current = api.get(url).json()
    assert current["canonical_name"] == "Shree Traders"
    assert current["tds_section"] == "194C"


def test_a_save_that_sends_no_version_still_works(api, client_record, party):
    url = f"{V1}/clients/{client_record.pk}/parties/{party['id']}/"
    assert api.patch(url, {"canonical_name": "No version sent"}, format="json").status_code == 200


def test_a_ledger_save_with_a_stale_version_is_refused(api, client_record, ledger):
    url = f"{V1}/clients/{client_record.pk}/ledgers/{ledger['id']}/"
    assert api.patch(url, {"is_active": False, "expected_version": ledger["version"]}, format="json").status_code == 200
    late = api.patch(url, {"is_active": True, "expected_version": ledger["version"]}, format="json")
    assert late.status_code == 409
    assert late.json()["code"] == "stale_edit"
    assert api.get(url).json()["is_active"] is False
