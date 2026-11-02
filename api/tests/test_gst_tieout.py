"""GST on the invoices against GST in the books: the per-head difference and the month-by-month working."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def tieout(api, client, fy=2025):
    done = api.get(f"{base(client)}/reports/gst-tieout/", {"fy": fy})
    assert done.status_code == 200, done.content
    return done.json()


def heads(body):
    return {(h["side"], h["head"]): h for h in body["heads"]}


def test_a_client_with_no_invoices_agrees_and_shows_nothing(api, client_record):
    body = tieout(api, client_record)
    assert body["agrees"] is True and body["heads"] == [] and body["months"] == []


def test_invoice_tax_and_ledger_tax_agree_head_by_head(api, client_record):
    vendor = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    assert post_bill(api, client_record, voucher(vendor, purchases)).status_code == 201
    done = post_bill(
        api, client_record,
        voucher(customer, sales, kind="SALES", reference="S-1", cgst_paise=450_000, sgst_paise=450_000, heads=[{"ledger": sales["id"], "amount_paise": 5_000_000}]),
    )
    assert done.status_code == 201, done.content
    body = tieout(api, client_record)
    found = heads(body)
    assert found[("input", "CGST")]["invoices_paise"] == 900_000 and found[("input", "CGST")]["books_paise"] == 900_000
    assert found[("output", "SGST")]["invoices_paise"] == 450_000 and found[("output", "SGST")]["difference_paise"] == 0
    assert body["agrees"] is True
    assert body["net"] == {"output_paise": 900_000, "input_paise": 1_800_000, "payable_paise": -900_000}
    (month,) = body["months"]
    assert month["month"] == "2025-10" and month["outward_taxable_paise"] == 5_000_000 and month["inward_taxable_paise"] == 10_000_000


def test_a_credit_note_takes_tax_off_the_output(api, client_record):
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    sale = voucher(customer, sales, kind="SALES", reference="S-1", cgst_paise=450_000, sgst_paise=450_000, heads=[{"ledger": sales["id"], "amount_paise": 5_000_000}])
    assert post_bill(api, client_record, sale).status_code == 201
    note = voucher(customer, sales, kind="CREDIT_NOTE", reference="CN-1", cgst_paise=90_000, sgst_paise=90_000, heads=[{"ledger": sales["id"], "amount_paise": 1_000_000}])
    assert post_bill(api, client_record, note).status_code == 201
    body = tieout(api, client_record)
    assert heads(body)[("output", "CGST")]["invoices_paise"] == 360_000 and body["agrees"] is True


def test_a_journal_posted_straight_to_a_gst_ledger_shows_as_a_difference(api, client_record, firm):
    from classify.models import LedgerAccount, LedgerGroup
    from core.db.session import firm_context
    from ledger.tests.support import post

    vendor = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    post_bill(api, client_record, voucher(vendor, purchases))
    import datetime

    with firm_context(firm.pk):
        gst = LedgerAccount.objects.get(client=client_record, name="Input CGST")
        other = LedgerAccount.objects.create(firm=firm, client=client_record, name="Misc", group=LedgerGroup.INDIRECT_EXPENSE)
        post(client_record, datetime.date(2025, 11, 1), gst, other, 100_000)
    body = tieout(api, client_record)
    assert heads(body)[("input", "CGST")]["difference_paise"] == 100_000 and body["agrees"] is False
