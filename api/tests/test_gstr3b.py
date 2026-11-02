"""The GSTR-3B working for a month: outward, reverse charge, credit and what is payable."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def month(api, client, m="2025-10"):
    done = api.get(f"{base(client)}/reports/gstr3b/", {"month": m})
    assert done.status_code == 200, done.content
    return done.json()


def test_a_sale_and_a_purchase_give_outward_tax_credit_and_the_payable(api, client_record):
    vendor = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    post_bill(api, client_record, voucher(vendor, purchases))
    post_bill(
        api, client_record,
        voucher(customer, sales, kind="SALES", reference="S-1", cgst_paise=1_350_000, sgst_paise=1_350_000, heads=[{"ledger": sales["id"], "amount_paise": 15_000_000}]),
    )
    body = month(api, client_record)
    assert body["outward_taxable"]["taxable_paise"] == 15_000_000 and body["outward_taxable"]["cgst_paise"] == 1_350_000
    assert body["itc_all_other"]["cgst_paise"] == 900_000
    assert body["payable"]["cgst_paise"] == 450_000 and body["payable"]["sgst_paise"] == 450_000
    assert body["counts"] == {"sales": 1, "purchases": 1, "reverse_charge": 0}


def test_another_month_is_empty_and_a_bad_month_is_refused(api, client_record):
    post = month(api, client_record, "2025-11")
    assert post["outward_taxable"]["taxable_paise"] == 0 and post["payable"]["igst_paise"] == 0
    assert api.get(f"{base(client_record)}/reports/gstr3b/", {"month": "2025-13"}).status_code == 400
    assert api.get(f"{base(client_record)}/reports/gstr3b/").status_code == 400
