"""TDS deducted by purchases, deposited by bank payments, and the challan that says how."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from api.tests.test_settlement_api import the_payment

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


@pytest.fixture
def deducted(api, client_record):
    """A contractor's invoice of Rs 10,00,000 that deducted Rs 1,00,000 TDS under 194C on 10 May 2025."""
    party = make_party(api, client_record)
    works = make_ledger(api, client_record, "Contract Work", "DIRECT_EXPENSE")
    body = voucher(
        party, works, reference="C-1", bill_date="2025-05-10", cgst_paise=0, sgst_paise=0,
        heads=[{"ledger": works["id"], "amount_paise": 10_00_000_00}], tds_paise=1_00_000_00, tds_section="194C",
    )
    response = post_bill(api, client_record, body)
    assert response.status_code == 201, response.content


def deposit(api, client_record):
    """The statement's payment, posted to TDS Payable: the money paid in to the tax department."""
    row = the_payment(client_record)
    payable = api.get(f"{base(client_record)}/ledgers/", {"page_size": 200}).json()
    ledger = next(r for r in payable["results"] if r["name"] == "TDS Payable")
    api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": ledger["id"], "learn": False}, format="json")
    posted = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")
    assert posted.status_code == 201, posted.content
    return posted.json()[0]["id"]


def summary(api, client_record):
    return api.get(f"{base(client_record)}/tds/summary/").json()


def kinds(api, client_record):
    return {k["kind"]: k["count"] for k in api.get(f"{base(client_record)}/open-items/").json()["kinds"]}


def challan(api, client_record, entry, **over):
    body = {"entry": entry, "section": "194C", "bsr_code": "0510308", "serial": "00123", "paid_on": "2025-06-05", **over}
    return api.post(f"{base(client_record)}/tds/", body, format="json")


def test_a_deduction_shows_by_section_and_month_and_is_late_until_deposited(api, client_record, deducted):
    body = summary(api, client_record)

    (month,) = body["months"]
    assert (month["section"], month["year"], month["month"], month["quarter"]) == ("194C", 2025, 5, 1)
    assert month["deducted_paise"] == 1_00_000_00 and month["unpaid_paise"] == 1_00_000_00
    assert month["due"] == "2025-06-07" and month["overdue"] is True
    assert kinds(api, client_record)["tds_not_deposited"] == 1


def test_a_payment_with_no_challan_is_listed_until_the_challan_is_recorded(api, client_record, statement, deducted):
    entry = deposit(api, client_record)
    assert kinds(api, client_record)["tds_payment_without_challan"] == 1
    assert summary(api, client_record)["payments_without_challan"][0]["entry"] == entry

    made = challan(api, client_record, entry)

    assert made.status_code == 201, made.content
    after = summary(api, client_record)
    assert after["payments_without_challan"] == []
    assert after["months"][0]["unpaid_paise"] == 0 and after["months"][0]["deposited_paise"] == 1_00_000_00
    counts = kinds(api, client_record)
    assert counts["tds_payment_without_challan"] == 0 and counts["tds_not_deposited"] == 0


def test_a_challan_for_another_section_does_not_clear_this_one(api, client_record, statement, deducted):
    entry = deposit(api, client_record)

    challan(api, client_record, entry, section="194J")

    assert summary(api, client_record)["months"][0]["unpaid_paise"] == 1_00_000_00


@pytest.mark.parametrize("over,words", [({"bsr_code": "12"}, "BSR code"), ({"serial": "1"}, "serial"), ({"section": ""}, "section")])
def test_a_malformed_challan_says_what_is_wrong(api, client_record, statement, deducted, over, words):
    entry = deposit(api, client_record)

    response = challan(api, client_record, entry, **over)

    assert response.status_code in (400, 422) and words in str(response.json())


def test_a_payment_not_booked_to_tds_payable_is_not_a_deposit(api, client_record, statement):
    row = the_payment(client_record)
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")
    api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": expense["id"], "learn": False}, format="json")
    entry = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json").json()[0]["id"]

    refused = challan(api, client_record, entry)

    assert refused.status_code == 422 and "not booked to TDS Payable" in refused.json()["detail"]


def test_one_challan_per_payment(api, client_record, statement, deducted):
    entry = deposit(api, client_record)
    challan(api, client_record, entry)

    again = challan(api, client_record, entry)

    assert again.status_code == 422 and "already recorded" in again.json()["detail"]


def test_a_read_only_member_may_look_but_not_record(api, client_record, statement, deducted, reader):
    entry = deposit(api, client_record)
    viewer = sign_in(reader.user)

    assert viewer.get(f"{base(client_record)}/tds/summary/").status_code == 200
    assert challan(viewer, client_record, entry).status_code == 403
