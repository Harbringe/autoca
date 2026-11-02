"""Group summary and a ledger month by month: they read the same balances as the Trial Balance and must agree with it."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, valid_gstin, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def books(api, client_record):
    vendor = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin=valid_gstin("27AAAAA0000A1Z"))
    sales = make_ledger(api, client_record, "Sales", "SALES")
    assert post_bill(api, client_record, voucher(vendor, purchases)).status_code == 201
    later = voucher(vendor, purchases, reference="INV-2", bill_date="2025-12-03", heads=[{"ledger": purchases["id"], "amount_paise": 2_000_000}], cgst_paise=0, sgst_paise=0)
    assert post_bill(api, client_record, later).status_code == 201
    sale = {"kind": "SALES", "party": customer["id"], "reference": "S-1", "bill_date": "2025-10-05", "heads": [{"ledger": sales["id"], "amount_paise": 5_000_000}], "cgst_paise": 0, "sgst_paise": 0}
    assert post_bill(api, client_record, sale).status_code == 201
    return purchases, sales


def test_the_group_summary_totals_match_the_trial_balance(api, client_record, books):
    groups = api.get(f"{base(client_record)}/reports/group-summary/", {"fy": 2025}).json()
    tb = api.get(f"{base(client_record)}/reports/trial-balance/", {"fy": 2025}).json()
    assert groups["total_debit_paise"] == groups["total_credit_paise"], "every entry balances, so the groups do"
    by_group = {g["group"]: g for g in groups["groups"]}
    assert by_group["PURCHASE"]["debit_paise"] == 12_000_000 and by_group["PURCHASE"]["ledgers"][0]["name"] == "Purchases"
    assert by_group["SALES"]["credit_paise"] == 5_000_000
    tb_total = sum(r["debit_paise"] for r in tb["rows"])
    assert groups["total_debit_paise"] == tb_total


def test_a_ledger_month_by_month_ends_at_its_closing_balance(api, client_record, books):
    purchases, _ = books
    body = api.get(f"{base(client_record)}/reports/ledger-monthly/", {"fy": 2025, "ledger": purchases["id"]}).json()
    months = {m["month"]: m for m in body["months"]}
    assert [m["month"] for m in body["months"]][0] == "2025-04" and body["months"][-1]["month"] == "2026-03"
    assert months["2025-10"]["debit_paise"] == 10_000_000 and months["2025-12"]["debit_paise"] == 2_000_000
    assert months["2025-11"]["closing_paise"] == 10_000_000, "a month with no movement carries the balance on"
    assert body["closing_paise"] == 12_000_000 == body["total_debit_paise"]
    assert body["ledger"]["group_label"] == "Purchase Accounts"


def test_a_ledger_that_is_not_theirs_or_missing_is_refused(api, client_record):
    assert api.get(f"{base(client_record)}/reports/ledger-monthly/", {"fy": 2025}).status_code == 400
    assert api.get(f"{base(client_record)}/reports/ledger-monthly/", {"fy": 2025, "ledger": "00000000-0000-0000-0000-000000000000"}).status_code == 404
