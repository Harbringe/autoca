"""Checking a GSTIN against the portal (stub provider): the comparison, the cache, the allowance, and that nothing in the books moves."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from api.tests.test_bills import make_party
from core.identifiers import gstin_check_character
from core.models import Role
from core.provisioning import create_firm
from gst.models import GstinCheck
from integrations.gstverify.stub import StubGstinVerifier
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _g(first):
    return first + gstin_check_character(first)


ACTIVE = _g("27AAAPL1234C1Z")
CANCELLED = _g("27AAAPL1234C9Z")
UNKNOWN = _g("27AAAPL1234C8Z")
URL = "/api/v1/clients/{}/gst/gstin-check/"


@pytest.fixture(autouse=True)
def _stub(settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "gstverify": "integrations.gstverify.stub.StubGstinVerifier"}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def test_stub_reads_status_from_the_gstin():
    assert StubGstinVerifier().lookup(ACTIVE).status == "Active"
    assert StubGstinVerifier().lookup(CANCELLED).status == "Cancelled"


def test_a_typed_gstin_is_checked_and_the_answer_is_kept(api, client_record):
    body = api.post(URL.format(client_record.pk), {"gstin": ACTIVE}, format="json").json()
    assert body["outcome"] == "found" and body["status"] == "active" and body["from_cache"] is False
    assert body["details"]["legal_name"].startswith("STUB LEGAL NAME")
    assert GstinCheck.objects.count() == 1
    again = api.post(URL.format(client_record.pk), {"gstin": ACTIVE}, format="json").json()
    assert again["from_cache"] is True and GstinCheck.objects.count() == 1


def test_a_gstin_the_portal_does_not_know_is_said_so(api, client_record):
    body = api.post(URL.format(client_record.pk), {"gstin": UNKNOWN}, format="json").json()
    assert body["outcome"] == "not_found" and "no record" in body["message"]


def _age(minutes):
    import datetime

    from django.utils import timezone

    GstinCheck.objects.update(checked_at=timezone.now() - datetime.timedelta(minutes=minutes))


def test_refresh_asks_the_portal_again_but_not_within_the_hour(api, client_record):
    api.post(URL.format(client_record.pk), {"gstin": ACTIVE}, format="json")
    soon = api.post(URL.format(client_record.pk), {"gstin": ACTIVE, "refresh": True}, format="json").json()
    assert soon["from_cache"] is True
    _age(90)
    body = api.post(URL.format(client_record.pk), {"gstin": ACTIVE, "refresh": True}, format="json").json()
    assert body["from_cache"] is False and GstinCheck.objects.count() == 1


def test_a_party_is_compared_with_the_portal_and_a_cancelled_gstin_is_flagged(api, client_record):
    party = make_party(api, client_record, name="Stub Trade Name AAAPL1234C", gstin=CANCELLED)
    body = api.post(URL.format(client_record.pk), {"party": party["id"]}, format="json").json()
    assert body["party_name"] == "Stub Trade Name AAAPL1234C"
    assert body["cancelled"] is True
    other = make_party(api, client_record, name="Quite Different Name", gstin=ACTIVE)
    body = api.post(URL.format(client_record.pk), {"party": other["id"]}, format="json").json()
    assert body["name_matches"] is False and body["cancelled"] is False


def test_nothing_in_the_books_changes(api, client_record):
    party = make_party(api, client_record, name="Quite Different Name", gstin=ACTIVE)
    api.post(URL.format(client_record.pk), {"party": party["id"]}, format="json")
    after = api.get(f"/api/v1/clients/{client_record.pk}/parties/{party['id']}/").json()
    assert after["canonical_name"] == "Quite Different Name"


def test_a_malformed_gstin_and_an_empty_request_are_refused(api, client_record):
    bad = api.post(URL.format(client_record.pk), {"gstin": "NOTAGSTIN"}, format="json")
    assert bad.status_code == 409 and bad.json()["code"] == "gst_rule"
    assert api.post(URL.format(client_record.pk), {}, format="json").status_code == 400


def test_the_monthly_allowance_counts_every_live_lookup_refreshes_included(api, client_record, settings):
    settings.GSTIN_CHECKS_PER_MONTH = 2
    post = lambda **b: api.post(URL.format(client_record.pk), b, format="json")  # noqa: E731
    assert post(gstin=ACTIVE).json()["from_cache"] is False
    _age(90)
    assert post(gstin=ACTIVE, refresh=True).json()["from_cache"] is False  # the second lookup, same GSTIN
    _age(90)
    stopped = post(gstin=ACTIVE, refresh=True).json()  # a third would pass the allowance: last answer, no call
    assert stopped["from_cache"] is True and "allowance" in stopped["message"]
    blocked = post(gstin=CANCELLED)
    assert blocked.status_code == 409 and "allowance" in blocked.json()["detail"]


def test_a_party_without_a_gstin_says_so(api, client_record):
    party = make_party(api, client_record, name="No Gstin Person", gstin="")
    response = api.post(URL.format(client_record.pk), {"party": party["id"]}, format="json")
    assert response.status_code == 409 and "no GSTIN" in response.json()["detail"]


def test_another_firms_party_is_not_found(api, client_record):
    other_api = sign_in(member(create_firm("Other Firm"), Role.FIRM_ADMIN, email="x@other.example").user)
    assert other_api.post(URL.format(client_record.pk), {"gstin": ACTIVE}, format="json").status_code == 404
