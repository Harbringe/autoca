"""A client's number formats: listed for every series, changed in one request, shown with the number they will give next."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


def url(client, *tail):
    return f"{V1}/clients/{client.pk}/numbering/" + "".join(f"{t}/" for t in tail)


def rows(api, client, fy=2025):
    return {(r["voucher_type"], r["type_name"]): r for r in api.get(url(client) + f"?fy={fy}").json()}


def test_every_standard_series_is_listed_with_no_format_and_its_next_number(api, client_record):
    listed = rows(api, client_record)
    assert {vt for vt, name in listed if name == ""} == {"Payment", "Receipt", "Contra", "Journal", "Purchase", "Sales", "Debit Note", "Credit Note"}
    assert listed[("Sales", "")] == {"voucher_type": "Sales", "type_name": "", "prefix": "", "padding": 0, "example": "1"}


def test_a_format_is_set_and_the_example_follows_it(api, client_record):
    saved = api.put(
        url(client_record), [{"voucher_type": "Sales", "type_name": "", "prefix": "S/{fy}/", "padding": 4}], format="json"
    )
    assert saved.status_code == 200
    assert rows(api, client_record)[("Sales", "")]["example"] == "S/25-26/0001"
    assert rows(api, client_record, fy=2026)[("Sales", "")]["example"] == "S/26-27/0001"


def test_clearing_a_format_removes_it(api, client_record):
    api.put(url(client_record), [{"voucher_type": "Sales", "type_name": "", "prefix": "S/", "padding": 3}], format="json")
    api.put(url(client_record), [{"voucher_type": "Sales", "type_name": "", "prefix": "", "padding": 0}], format="json")
    assert rows(api, client_record)[("Sales", "")]["example"] == "1"


def test_a_firms_own_voucher_type_is_a_series_with_its_own_format(api, client_record):
    api.post(f"{V1}/clients/{client_record.pk}/voucher-types/", {"name": "GST SALE", "parent": "Sales"}, format="json")
    api.put(url(client_record), [{"voucher_type": "Sales", "type_name": "GST SALE", "prefix": "G", "padding": 2}], format="json")
    listed = rows(api, client_record)
    assert listed[("Sales", "GST SALE")]["example"] == "G01"
    assert listed[("Sales", "")]["example"] == "1", "the standard Sales series is not touched"


@pytest.mark.parametrize(
    "item",
    [
        {"voucher_type": "Sales", "type_name": "", "prefix": "S/", "padding": 12},
        {"voucher_type": "Sales", "type_name": "", "prefix": "has space", "padding": 2},
        {"voucher_type": "Sales", "type_name": "", "prefix": "x" * 17, "padding": 2},
        {"voucher_type": "Sales", "type_name": "", "prefix": "{bad}", "padding": 2},
        {"voucher_type": "Sales", "type_name": "No Such Type", "prefix": "S", "padding": 2},
    ],
)
def test_a_format_that_is_not_allowed_is_refused_and_nothing_is_saved(api, client_record, item):
    assert api.put(url(client_record), [item], format="json").status_code == 400
    assert rows(api, client_record)[("Sales", "")]["prefix"] == ""
