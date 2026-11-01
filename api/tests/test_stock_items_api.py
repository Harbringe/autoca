"""The client's stock items: the master list with unit, HSN, GST rate and reorder level, kept by a person and audited."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from api.tests.test_bills import base, make_ledger
from core.models import Role

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def url(client, tail=""):
    return f"{base(client)}/stock-items/{tail}"


def make(api, client, name="Mustard Oil 1L", **over):
    body = {"name": name, "unit": "Nos", "hsn_sac": "1514", "gst_rate": "5", "reorder_level": "20", **over}
    return api.post(url(client), body, format="json")


def test_an_item_is_made_listed_changed_and_removed(api, client_record):
    made = make(api, client_record)
    assert made.status_code == 201, made.json()
    item = made.json()
    assert (item["name"], item["unit"], item["hsn_sac"], item["gst_rate"], item["reorder_level"]) == ("Mustard Oil 1L", "Nos", "1514", "5.00", "20.000")
    assert [i["name"] for i in api.get(url(client_record)).json()["results"]] == ["Mustard Oil 1L"]
    changed = api.patch(url(client_record, f"{item['id']}/"), {"reorder_level": "35", "unit": "Ltr"}, format="json")
    assert changed.status_code == 200 and changed.json()["reorder_level"] == "35.000" and changed.json()["unit"] == "Ltr"
    assert api.delete(url(client_record, f"{item['id']}/")).status_code == 204
    assert api.get(url(client_record)).json()["results"] == []


def test_two_items_cannot_share_a_name(api, client_record):
    assert make(api, client_record).status_code == 201
    again = make(api, client_record, name="  mustard   oil 1L ")
    assert again.status_code == 400 and "name" in again.json()["fields"] or "name" in again.json()


def test_the_rates_and_levels_are_checked(api, client_record):
    assert make(api, client_record, name="A", gst_rate="150").status_code == 400
    assert make(api, client_record, name="B", reorder_level="-1").status_code == 400
    assert make(api, client_record, name="C", name_hint="x").status_code == 201, "an unknown field is ignored, not an error"


def test_the_purchase_and_sales_ledgers_must_be_this_clients(api, firm, client_record):
    import datetime

    from core.provisioning import create_client

    other = create_client(firm, "Other Client", datetime.date(2025, 4, 1))
    theirs = make_ledger(api, other, "Their Sales", "SALES")
    refused = make(api, client_record, sales_ledger=theirs["id"])
    assert refused.status_code == 400
    mine = make_ledger(api, client_record, "My Sales", "SALES")
    assert make(api, client_record, name="D", sales_ledger=mine["id"]).status_code == 201


def test_every_change_is_in_the_audit_trail(api, client_record):
    item = make(api, client_record).json()
    api.patch(url(client_record, f"{item['id']}/"), {"reorder_level": "35"}, format="json")
    api.delete(url(client_record, f"{item['id']}/"))
    rows = api.get(f"{base(client_record)}/audit-trail/?kind=ITEM").json()["results"]
    assert [(r["action"], r["label"]) for r in rows] == [
        ("REMOVED", "Stock item: Mustard Oil 1L"),
        ("EDITED", "Stock item: Mustard Oil 1L"),
        ("CREATED", "Stock item: Mustard Oil 1L"),
    ]


def test_a_read_only_person_may_read_but_not_change(firm, client_record, api):
    item = make(api, client_record).json()
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert reader.get(url(client_record)).status_code == 200
    assert reader.post(url(client_record), {"name": "X"}, format="json").status_code == 403
    assert reader.patch(url(client_record, f"{item['id']}/"), {"unit": "Kg"}, format="json").status_code == 403
    assert reader.delete(url(client_record, f"{item['id']}/")).status_code == 403
