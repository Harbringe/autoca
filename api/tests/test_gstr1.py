"""The GSTR-1 working for a month: B2B, B2C, credit notes, documents, and agreement with the 3B outward figure."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, valid_gstin

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def gstr1(api, client, m="2025-10"):
    done = api.get(f"{base(client)}/reports/gstr1/", {"month": m})
    assert done.status_code == 200, done.content
    return done.json()


def sale(party, ledger, ref, taxable, *, kind="SALES", cgst=0, sgst=0, igst=0):
    return {
        "kind": kind, "party": party["id"], "reference": ref, "bill_date": "2025-10-05",
        "heads": [{"ledger": ledger["id"], "amount_paise": taxable}], "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
    }


@pytest.fixture
def parties(api, client_record):
    registered = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin=valid_gstin("27AAAAA0000A1Z"))
    walk_in = make_party(api, client_record, "Walk In", role="CUSTOMER", gstin="")
    return registered, walk_in, make_ledger(api, client_record, "Sales", "SALES")


def test_sales_fall_into_b2b_b2cl_and_b2cs_and_agree_with_the_3b_outward_figure(api, client_record, parties):
    registered, walk_in, sales = parties
    assert post_bill(api, client_record, sale(registered, sales, "B-1", 10_000_00, cgst=90_000, sgst=90_000)).status_code == 201
    assert post_bill(api, client_record, sale(walk_in, sales, "C-1", 3_000_000_00 // 10, igst=54_000_00)).status_code == 201  # large, inter-state
    assert post_bill(api, client_record, sale(walk_in, sales, "C-2", 5_000_00, cgst=45_000, sgst=45_000)).status_code == 201
    body = gstr1(api, client_record)
    assert [r["number"] for r in body["b2b"]["rows"]] == ["B-1"] and body["b2b"]["rows"][0]["gstin"]
    assert [r["number"] for r in body["b2cl"]["rows"]] == ["C-1"]
    assert body["b2cs"]["rows"] == [{"supply": "Intra-state", "rate": "18", "taxable_paise": 5_000_00, "igst_paise": 0, "cgst_paise": 45_000, "sgst_paise": 45_000, "cess_paise": 0}]
    assert body["agrees_with_3b"] is True
    assert body["documents"] == [{"label": "Invoices for outward supply", "from": "B-1", "to": "C-2", "count": 3}]


def test_a_credit_note_is_listed_with_the_sign_of_a_reduction_and_taxless_sales_go_to_table_8(api, client_record, parties):
    registered, walk_in, sales = parties
    post_bill(api, client_record, sale(registered, sales, "B-1", 10_000_00, cgst=90_000, sgst=90_000))
    assert post_bill(api, client_record, sale(registered, sales, "CN-1", 1_000_00, kind="CREDIT_NOTE", cgst=9_000, sgst=9_000)).status_code == 201
    post_bill(api, client_record, sale(walk_in, sales, "X-1", 2_000_00))
    body = gstr1(api, client_record)
    assert body["credit_notes_registered"]["rows"][0]["taxable_paise"] == -1_000_00
    assert body["exempt_nil_non_gst"]["untaxed_sales_paise"] == 2_000_00
    assert body["agrees_with_3b"] is True


def test_a_bad_month_is_refused(api, client_record):
    assert api.get(f"{base(client_record)}/reports/gstr1/", {"month": "2025-00"}).status_code == 400
