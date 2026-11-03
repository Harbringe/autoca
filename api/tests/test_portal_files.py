"""The GSTR-1 offline-tool JSON and the EPFO ECR file: built from the workings, with what is missing named."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, valid_gstin
from api.tests.test_payroll import add, line, run

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

BUYER = valid_gstin("27AAAAA0000A1Z")


def sale(party, ledger, ref, taxable, *, kind="SALES", cgst=0, sgst=0, igst=0):
    return {
        "kind": kind, "party": party["id"], "reference": ref, "bill_date": "2025-10-05",
        "heads": [{"ledger": ledger["id"], "amount_paise": taxable}], "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
    }


def gstr1_file(api, client, month="2025-10"):
    done = api.get(f"{base(client)}/reports/gstr1/file/", {"month": month})
    assert done.status_code == 200, done.content
    return done.json()


def test_the_gstr1_file_carries_b2b_b2cs_and_credit_notes_in_the_portals_shape_and_lists_what_is_missing(api, client_record):
    registered = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin=BUYER)
    walk_in = make_party(api, client_record, "Walk In", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    assert post_bill(api, client_record, sale(registered, sales, "B-1", 10_000_00, cgst=90_000, sgst=90_000)).status_code == 201
    assert post_bill(api, client_record, sale(walk_in, sales, "C-1", 5_000_00, cgst=45_000, sgst=45_000)).status_code == 201
    assert post_bill(api, client_record, sale(registered, sales, "CN-1", 1_000_00, kind="CREDIT_NOTE", cgst=9_000, sgst=9_000)).status_code == 201
    body = gstr1_file(api, client_record)
    out = body["json"]
    assert out["fp"] == "102025"
    (b2b,) = out["b2b"]
    assert b2b["ctin"] == BUYER
    inv = b2b["inv"][0]
    assert (inv["inum"], inv["idt"], inv["val"], inv["pos"], inv["inv_typ"]) == ("B-1", "05-10-2025", 11800.0, "27", "R")
    assert inv["itms"][0]["itm_det"] == {"rt": 18.0, "txval": 10000.0, "iamt": 0.0, "camt": 900.0, "samt": 900.0, "csamt": 0.0}
    assert out["b2cs"][0]["sply_ty"] == "INTRA" and out["b2cs"][0]["txval"] == 5000.0
    note = out["cdnr"][0]["nt"][0]
    assert (note["ntty"], note["nt_num"], note["val"]) == ("C", "CN-1", 1180.0), "a credit note is listed with positive amounts"
    assert out["doc_issue"]["doc_det"][0]["docs"][0]["totnum"] == 2
    text = " ".join(body["missing"])
    assert "aggregate turnover" in text.lower() and "GSTIN" in text, "no GST registration is recorded for the client"


def test_a_month_with_no_sales_gives_an_empty_file_and_a_bad_month_is_refused(api, client_record):
    body = gstr1_file(api, client_record, "2025-11")
    assert "b2b" not in body["json"] and body["json"]["fp"] == "112025"
    assert api.get(f"{base(client_record)}/reports/gstr1/file/", {"month": "2025-13"}).status_code == 400


def ecr(api, client, year=2025, month=5):
    return api.get(f"{base(client)}/payroll/ecr/", {"year": year, "month": month})


def test_the_ecr_has_one_line_per_member_with_the_epf_eps_split_in_whole_rupees(api, client_record):
    asha = add(api, client_record, "Asha Rao")
    made = run(api, client_record, [line(asha, gross_paise=12_000_00, pf_employee_paise=1_440_00, pf_employer_paise=1_440_00, tds_paise=0)])
    assert made.status_code == 201, made.content
    refused = ecr(api, client_record)
    assert refused.status_code == 400 and "Asha Rao" in str(refused.json()), "no UAN yet"
    employees = api.get(f"{base(client_record)}/employees/").json()["results"]
    api.patch(f"{base(client_record)}/employees/{employees[0]['id']}/", {"uan": "100200300400"}, format="json")
    done = ecr(api, client_record)
    assert done.status_code == 200 and done["Content-Type"].startswith("text/plain") and "attachment" in done["Content-Disposition"]
    fields = done.content.decode().strip().split("#~#")
    assert fields == ["100200300400", "ASHA RAO", "12000", "12000", "12000", "12000", "1440", "1000", "440", "0", "0"]


def test_the_ecr_for_a_month_with_no_run_or_no_pf_is_refused_in_words(api, client_record):
    assert ecr(api, client_record).status_code == 400
    bad = api.get(f"{base(client_record)}/payroll/ecr/", {"year": 2025, "month": 13})
    assert bad.status_code == 400
