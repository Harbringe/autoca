"""The stock-against-the-books check: it reads the register, the stock ledgers and the item list, and writes nothing."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def check(api, client, fy=2025):
    done = api.get(f"{base(client)}/reports/stock-reconciliation/", {"fy": fy})
    assert done.status_code == 200, done.content
    body = done.json()
    return body, {c["key"]: c for c in body["checks"]}


def opening(api, client, name="Mustard Oil 1L", qty="40", value=4_000_00):
    made = api.post(
        f"{base(client)}/stock-entries/",
        {"kind": "OPENING", "entry_date": "2025-04-01", "direction": "IN", "name": name, "unit": "Nos", "quantity": qty, "value_paise": value},
        format="json",
    )
    assert made.status_code == 201, made.content


def test_an_empty_client_agrees(api, client_record):
    body, checks = check(api, client_record)
    assert body["agrees"] is True and body["difference_paise"] == 0
    assert checks["value"]["status"] == "ok"


def test_stock_in_the_register_that_the_books_do_not_carry_is_named_with_the_gap(api, client_record):
    opening(api, client_record)
    body, checks = check(api, client_record)
    assert body["register_value_paise"] == 4_000_00 and body["books_value_paise"] == 0 and body["difference_paise"] == 4_000_00
    assert checks["value"]["status"] == "attention" and "lower" in checks["value"]["message"]
    assert body["agrees"] is False


def test_an_item_not_on_the_list_is_named_and_listing_it_clears_the_check(api, client_record):
    opening(api, client_record)
    _, checks = check(api, client_record)
    assert checks["unlisted"]["status"] == "attention" and checks["unlisted"]["examples"] == ["Mustard Oil 1L"]
    api.post(f"{base(client_record)}/stock-items/", {"name": "mustard oil 1l", "unit": "Nos"}, format="json")
    _, checks = check(api, client_record)
    assert checks["unlisted"]["status"] == "ok"


def test_a_unit_that_differs_from_the_list_is_named(api, client_record):
    opening(api, client_record)
    api.post(f"{base(client_record)}/stock-items/", {"name": "Mustard Oil 1L", "unit": "Ltr"}, format="json")
    _, checks = check(api, client_record)
    assert checks["unit"]["status"] == "attention" and "Ltr" in checks["unit"]["examples"][0]


def test_the_check_writes_nothing(api, client_record):
    opening(api, client_record)
    check(api, client_record)
    assert len(api.get(f"{base(client_record)}/stock-entries/").json()["results"]) == 1
    assert api.get(f"{base(client_record)}/stock-items/").json()["results"] == []
