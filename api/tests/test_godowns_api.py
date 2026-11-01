"""Godowns (stock locations), moving stock between them, and a physical count that books the difference."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_bills import base
from core.provisioning import create_client

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def godowns(client, tail=""):
    return f"{base(client)}/godowns/{tail}"


def entries(client, tail=""):
    return f"{base(client)}/stock-entries/{tail}"


def make_godown(api, client, name="Main Warehouse"):
    made = api.post(godowns(client), {"name": name}, format="json")
    assert made.status_code == 201, made.json()
    return made.json()


def opening(api, client, qty="100", value=50_000_00, godown=None, name="Widget", date="2025-04-01"):
    body = {"kind": "OPENING", "entry_date": date, "name": name, "unit": "pcs", "quantity": qty, "value_paise": value}
    if godown:
        body["godown"] = godown
    made = api.post(entries(client), body, format="json")
    assert made.status_code == 201, made.json()
    return made.json()


def report(api, client, **query):
    return api.get(f"{base(client)}/reports/inventory/", {"fy": 2025, **query}).json()


def test_godowns_are_made_listed_renamed_and_removed(api, client_record):
    shop = make_godown(api, client_record, "Shop")
    assert [g["name"] for g in api.get(godowns(client_record)).json()["results"]] == ["Shop"]
    assert api.patch(godowns(client_record, f"{shop['id']}/"), {"name": "Shop floor"}, format="json").json()["name"] == "Shop floor"
    assert api.delete(godowns(client_record, f"{shop['id']}/")).status_code == 204


def test_two_godowns_cannot_share_a_name(api, client_record):
    make_godown(api, client_record, "Shop")
    again = api.post(godowns(client_record), {"name": " shop "}, format="json")
    assert again.status_code == 400


def test_a_godown_with_stock_in_it_cannot_be_removed(api, client_record):
    shop = make_godown(api, client_record, "Shop")
    opening(api, client_record, godown=shop["id"])
    refused = api.delete(godowns(client_record, f"{shop['id']}/"))
    assert refused.status_code in (400, 409), refused.content


def test_godown_changes_are_in_the_audit_trail(api, client_record):
    shop = make_godown(api, client_record, "Shop")
    api.patch(godowns(client_record, f"{shop['id']}/"), {"name": "Shop floor"}, format="json")
    rows = api.get(f"{base(client_record)}/audit-trail/?kind=GODOWN").json()["results"]
    assert [(r["action"], r["label"]) for r in rows] == [("EDITED", "Godown: Shop floor"), ("CREATED", "Godown: Shop")]


def test_stock_can_be_opened_in_a_godown_of_this_client_only(api, firm, client_record):
    other = create_client(firm, "Other Client", datetime.date(2025, 4, 1))
    theirs = make_godown(api, other, "Theirs")
    refused = api.post(entries(client_record), {"kind": "OPENING", "entry_date": "2025-04-01", "name": "Widget", "quantity": "5", "godown": theirs["id"]}, format="json")
    assert refused.status_code in (400, 422), refused.content


def transfer(api, client, src, dst, qty="30", date="2025-05-01", name="Widget"):
    return api.post(entries(client, "transfer/"), {"entry_date": date, "name": name, "unit": "pcs", "quantity": qty, "from_godown": src, "to_godown": dst}, format="json")


def test_a_transfer_moves_stock_between_godowns_without_changing_the_total(api, client_record):
    shop, yard = make_godown(api, client_record, "Shop"), make_godown(api, client_record, "Yard")
    opening(api, client_record, godown=shop["id"])
    assert transfer(api, client_record, shop["id"], yard["id"]).status_code == 201

    whole = report(api, client_record)
    (item,) = whole["items"]
    assert item["closing_qty"] == "100" and item["closing_value_paise"] == 50_000_00, "the business still holds the same stock"
    assert [m["source"] for m in item["movements"]] == ["Opening stock"], "a transfer is not a purchase or a sale"

    in_shop = report(api, client_record, godown=shop["id"])
    in_yard = report(api, client_record, godown=yard["id"])
    assert in_shop["items"][0]["closing_qty"] == "70" and in_yard["items"][0]["closing_qty"] == "30"
    assert in_yard["quantities_only"] is True and whole["quantities_only"] is False
    assert [m["source"] for m in in_yard["items"][0]["movements"]] == ["Stock transfer from Shop"]
    assert [m["source"] for m in in_shop["items"][0]["movements"]][-1] == "Stock transfer to Yard"


def test_stock_with_no_godown_is_the_main_location(api, client_record):
    yard = make_godown(api, client_record, "Yard")
    opening(api, client_record)
    assert transfer(api, client_record, None, yard["id"], qty="40").status_code == 201
    assert report(api, client_record, godown="none")["items"][0]["closing_qty"] == "60"
    assert report(api, client_record, godown=yard["id"])["items"][0]["closing_qty"] == "40"


def test_a_transfer_is_refused_when_it_goes_nowhere_or_to_another_clients_godown(api, firm, client_record):
    shop = make_godown(api, client_record, "Shop")
    assert transfer(api, client_record, shop["id"], shop["id"]).status_code in (400, 422)
    assert transfer(api, client_record, None, None).status_code in (400, 422)
    other = create_client(firm, "Other Client", datetime.date(2025, 4, 1))
    theirs = make_godown(api, other, "Theirs")
    assert transfer(api, client_record, shop["id"], theirs["id"]).status_code in (400, 422)
    assert transfer(api, client_record, shop["id"], None, qty="0").status_code in (400, 422)


def test_removing_a_transfer_takes_both_halves_back(api, client_record):
    shop, yard = make_godown(api, client_record, "Shop"), make_godown(api, client_record, "Yard")
    opening(api, client_record, godown=shop["id"])
    made = transfer(api, client_record, shop["id"], yard["id"]).json()
    first = made["entries"][0]["id"]
    assert api.post(entries(client_record, f"{first}/remove/"), {}, format="json").status_code == 204
    assert report(api, client_record, godown=yard["id"])["items"] == []
    assert report(api, client_record, godown=shop["id"])["items"][0]["closing_qty"] == "100"


def count(api, client, qty, date="2025-06-30", **extra):
    return api.post(entries(client, "count/"), {"entry_date": date, "name": "Widget", "unit": "pcs", "counted_quantity": qty, **extra}, format="json")


def test_a_count_that_finds_less_books_a_shortage(api, client_record):
    opening(api, client_record)
    done = count(api, client_record, "96")
    assert done.status_code == 201, done.content
    body = done.json()
    assert body["book_quantity"] == "100" and body["difference"] == "-4"
    assert body["entry"]["direction"] == "OUT" and body["entry"]["quantity"] == "4.000" and body["entry"]["note"].startswith("Physical count")
    assert report(api, client_record)["items"][0]["closing_qty"] == "96"


def test_a_count_that_finds_more_books_a_surplus_at_the_average_cost(api, client_record):
    opening(api, client_record, qty="100", value=50_000_00)
    body = count(api, client_record, "104").json()
    assert body["difference"] == "4" and body["entry"]["direction"] == "IN"
    assert body["entry"]["value_paise"] == 2_000_00, "4 at the average of 500 each"


def test_a_count_that_agrees_books_nothing(api, client_record):
    opening(api, client_record)
    done = count(api, client_record, "100")
    assert done.status_code == 200 and done.json()["difference"] == "0" and done.json()["entry"] is None
    assert len(api.get(entries(client_record)).json()["results"]) == 1


def test_a_count_in_a_godown_compares_with_that_godown_only(api, client_record):
    shop, yard = make_godown(api, client_record, "Shop"), make_godown(api, client_record, "Yard")
    opening(api, client_record, qty="100", godown=shop["id"])
    transfer(api, client_record, shop["id"], yard["id"], qty="30")
    body = count(api, client_record, "28", godown=yard["id"]).json()
    assert body["book_quantity"] == "30" and body["difference"] == "-2"
    assert report(api, client_record)["items"][0]["closing_qty"] == "98"
