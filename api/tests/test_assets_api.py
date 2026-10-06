"""The asset register: tied to a purchase the books hold, and depreciated from its terms."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def machine_purchase(api, client_record):
    """A purchase that put Rs 10,00,000 on a Machinery ledger."""
    party = make_party(api, client_record)
    machinery = make_ledger(api, client_record, "Machinery", "FIXED_ASSET")
    body = voucher(
        party, machinery, reference="M-1", bill_date="2025-04-01", cgst_paise=0, sgst_paise=0,
        heads=[{"ledger": machinery["id"], "amount_paise": 10_00_000_00}],
    )
    response = post_bill(api, client_record, body)
    assert response.status_code == 201, response.content
    return machinery, response.json()


def register(api, client_record, ledger, bill=None, **over):
    body = {
        "name": "Lathe", "ledger": ledger["id"], "bill": bill["id"] if bill else None, "cost_paise": 10_00_000_00,
        "put_to_use": "2025-04-01", "method": "SLM", "life_years": 10, **over,
    }
    return api.post(f"{base(client_record)}/assets/", body, format="json")


def open_items(api, client_record, kind):
    return api.get(f"{base(client_record)}/open-items/", {"kind": kind}).json()["items"]


def test_a_purchase_of_a_fixed_asset_is_an_open_item_until_it_is_registered(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    assert len(open_items(api, client_record, "fixed_asset_unregistered")) == 1

    made = register(api, client_record, machinery, bill)

    assert made.status_code == 201, made.content
    assert open_items(api, client_record, "fixed_asset_unregistered") == []


def test_the_schedule_charges_the_year_from_the_terms(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    register(api, client_record, machinery, bill)

    schedule = api.get(f"{base(client_record)}/assets/schedule/", {"fy": 2025}).json()

    (row,) = schedule["rows"]
    assert row["depreciation_paise"] == 1_00_000_00 and row["closing_paise"] == 9_00_000_00
    assert schedule["total_depreciation_display"] == "₹1,00,000.00"
    second = api.get(f"{base(client_record)}/assets/schedule/", {"fy": 2026}).json()
    assert second["rows"][0]["opening_paise"] == 9_00_000_00


def test_the_cost_cannot_exceed_what_the_purchase_put_on_the_ledger(api, client_record, machine_purchase):
    machinery, bill = machine_purchase

    over = register(api, client_record, machinery, bill, cost_paise=10_00_000_01)

    assert over.status_code == 422 and over.json()["code"] == "asset_rule" and "at most" in over.json()["detail"]
    register(api, client_record, machinery, bill, cost_paise=6_00_000_00)
    again = register(api, client_record, machinery, bill, cost_paise=6_00_000_00)
    assert again.status_code == 422


def test_only_a_fixed_asset_ledger_will_do(api, client_record, machine_purchase):
    _, bill = machine_purchase
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")

    response = register(api, client_record, expense, bill)

    assert response.status_code == 422 and "not a fixed-asset ledger" in response.json()["detail"]


def test_a_sold_asset_is_depreciated_to_the_day_of_sale(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    asset = register(api, client_record, machinery, bill).json()

    sold = api.post(
        f"{base(client_record)}/assets/{asset['id']}/dispose/", {"disposed_on": "2025-09-30", "proceeds_paise": 8_00_000_00}, format="json"
    )

    assert sold.status_code == 200 and sold.json()["disposed_on"] == "2025-09-30"
    row = api.get(f"{base(client_record)}/assets/schedule/", {"fy": 2025}).json()["rows"][0]
    assert row["days_in_use"] == 183
    assert api.get(f"{base(client_record)}/assets/schedule/", {"fy": 2026}).json()["rows"] == []
    assert api.post(f"{base(client_record)}/assets/{asset['id']}/dispose/", {"disposed_on": "2025-10-31"}, format="json").status_code == 422


def test_a_bad_year_is_a_400_and_a_read_only_member_cannot_register(api, client_record, machine_purchase, reader):
    machinery, bill = machine_purchase

    assert api.get(f"{base(client_record)}/assets/schedule/", {"fy": "next"}).status_code == 400
    assert sign_in(reader.user).get(f"{base(client_record)}/assets/").status_code == 200
    denied = sign_in(reader.user).post(
        f"{base(client_record)}/assets/",
        {"name": "x", "ledger": machinery["id"], "cost_paise": 100, "put_to_use": "2025-04-01", "method": "SLM", "life_years": 5},
        format="json",
    )
    assert denied.status_code == 403
