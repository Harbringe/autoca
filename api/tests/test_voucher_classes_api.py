"""A client's voucher classes: a preset head ledger and GST rate for sales and purchase vouchers."""

from __future__ import annotations

import datetime

import pytest

from classify.models import LedgerGroup as G
from core.db.session import firm_context
from core.provisioning import create_client
from ledger.tests.support import make_ledger

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


def url(client, *tail):
    return f"{V1}/clients/{client.pk}/voucher-classes/" + "".join(f"{t}/" for t in tail)


@pytest.fixture
def sales_ledger(firm, client_record):
    with firm_context(firm.pk):
        return make_ledger(client_record, "Sales", G.SALES)


def listed(api, client):
    data = api.get(url(client)).json()
    return data["results"] if isinstance(data, dict) else data


def test_a_class_is_made_listed_changed_and_removed(api, client_record, sales_ledger):
    made = api.post(
        url(client_record),
        {"name": "Retail 18%", "voucher_type": "Sales", "head_ledger": str(sales_ledger.pk), "gst_rate": "18.00"},
        format="json",
    )
    assert made.status_code == 201
    assert [(c["name"], c["gst_rate"], c["head_ledger_name"]) for c in listed(api, client_record)] == [("Retail 18%", "18.00", "Sales")]
    assert api.patch(url(client_record, made.json()["id"]), {"gst_rate": "12.00"}, format="json").json()["gst_rate"] == "12.00"
    assert api.delete(url(client_record, made.json()["id"])).status_code == 204


def test_a_class_cannot_use_another_clients_ledger(api, firm, client_record):
    with firm_context(firm.pk):
        other = create_client(firm, "Other Client", datetime.date(2025, 4, 1))
        theirs = make_ledger(other, "Sales", G.SALES)
    refused = api.post(url(client_record), {"name": "X", "voucher_type": "Sales", "head_ledger": str(theirs.pk)}, format="json")
    assert refused.status_code == 400


@pytest.mark.parametrize(
    "extra",
    [{"voucher_type": "Journal"}, {"gst_rate": "120.00"}, {"gst_rate": "-1"}, {"type_name": "No Such Type"}],
)
def test_a_class_that_makes_no_sense_is_refused(api, client_record, sales_ledger, extra):
    body = {"name": "X", "voucher_type": "Sales", "head_ledger": str(sales_ledger.pk), **extra}
    assert api.post(url(client_record), body, format="json").status_code == 400


def test_a_class_may_belong_to_the_firms_own_voucher_type_it_counts_as(api, client_record, sales_ledger):
    api.post(f"{V1}/clients/{client_record.pk}/voucher-types/", {"name": "GST SALE", "parent": "Sales"}, format="json")
    body = {"name": "Retail", "voucher_type": "Sales", "type_name": "GST SALE", "head_ledger": str(sales_ledger.pk)}
    assert api.post(url(client_record), body, format="json").status_code == 201
    wrong_parent = {**body, "name": "Odd", "voucher_type": "Purchase"}
    assert api.post(url(client_record), wrong_parent, format="json").status_code == 400


def test_a_class_name_is_unique_per_client(api, client_record, sales_ledger):
    body = {"name": "Retail", "voucher_type": "Sales", "head_ledger": str(sales_ledger.pk)}
    api.post(url(client_record), body, format="json")
    assert api.post(url(client_record), body, format="json").status_code == 400
