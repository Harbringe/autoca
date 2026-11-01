"""A client's own voucher types: made, listed, changed and removed, and kept while vouchers use them."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from core.db.session import firm_context
from ledger.models import JournalEntry

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


def url(client, *tail):
    return f"{V1}/clients/{client.pk}/voucher-types/" + "".join(f"{t}/" for t in tail)


def use(firm, client, name):
    with firm_context(firm.pk):
        JournalEntry.objects.create(
            firm_id=firm.pk, client=client, entry_no=1, financial_year=2025, entry_date=datetime.date(2025, 4, 1),
            voucher_type="Sales", type_name=name, approved_at=timezone.now(),
        )


def test_a_voucher_type_is_made_listed_and_changed(api, firm, client_record):
    made = api.post(url(client_record), {"name": "GST SALE", "parent": "Sales"}, format="json")
    assert made.status_code == 201 and made.json()["name"] == "GST SALE" and made.json()["in_use"] is False
    listed = api.get(url(client_record)).json()
    rows = listed["results"] if isinstance(listed, dict) else listed
    assert [(r["name"], r["parent"]) for r in rows] == [("GST SALE", "Sales")]
    changed = api.patch(url(client_record, made.json()["id"]), {"name": "GST RETAIL"}, format="json")
    assert changed.status_code == 200 and changed.json()["name"] == "GST RETAIL"


def test_a_name_is_unique_per_client_and_may_not_shadow_a_standard_type(api, client_record):
    api.post(url(client_record), {"name": "GST SALE", "parent": "Sales"}, format="json")
    again = api.post(url(client_record), {"name": "GST SALE", "parent": "Sales"}, format="json")
    assert again.status_code == 400
    shadow = api.post(url(client_record), {"name": "Sales", "parent": "Sales"}, format="json")
    assert shadow.status_code == 400


def test_a_bank_voucher_type_cannot_have_its_own_series(api, client_record):
    refused = api.post(url(client_record), {"name": "Bank Payment", "parent": "Payment"}, format="json")
    assert refused.status_code == 400


def test_a_type_in_use_cannot_be_renamed_reparented_or_deleted(api, firm, client_record):
    made = api.post(url(client_record), {"name": "GST SALE", "parent": "Sales"}, format="json").json()
    use(firm, client_record, "GST SALE")
    assert api.get(url(client_record, made["id"])).json()["in_use"] is True
    assert api.patch(url(client_record, made["id"]), {"name": "Other"}, format="json").status_code == 409
    assert api.patch(url(client_record, made["id"]), {"parent": "Purchase"}, format="json").status_code == 409
    assert api.delete(url(client_record, made["id"])).status_code == 409


def test_an_unused_type_can_be_deleted(api, client_record):
    made = api.post(url(client_record), {"name": "Spare", "parent": "Journal"}, format="json").json()
    assert api.delete(url(client_record, made["id"])).status_code == 204
