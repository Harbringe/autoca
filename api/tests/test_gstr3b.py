"""The GSTR-3B working for a month: outward, entered supplies, credit carried forward and applied, and what is payable."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def url(client):
    return f"{base(client)}/reports/gstr3b/"


def month(api, client, m="2025-10"):
    done = api.get(url(client), {"month": m})
    assert done.status_code == 200, done.content
    return done.json()


def enter(api, client, m="2025-10", **body):
    return api.put(f"{url(client)}?month={m}", body, format="json")


def book(api, client, *, purchase_date=None, sale_tax=1_350_000):
    vendor = make_party(api, client)
    purchases = make_ledger(api, client)
    customer = make_party(api, client, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client, "Sales", "SALES")
    post_bill(api, client, voucher(vendor, purchases, **({"bill_date": purchase_date} if purchase_date else {})))
    return post_bill(
        api, client,
        voucher(customer, sales, kind="SALES", reference="S-1", cgst_paise=sale_tax, sgst_paise=sale_tax, heads=[{"ledger": sales["id"], "amount_paise": 15_000_000}]),
    )


def test_credit_is_applied_to_the_liability_and_the_rest_is_paid_in_cash(api, client_record):
    book(api, client_record)
    body = month(api, client_record)
    assert body["outward_taxable"]["taxable_paise"] == 15_000_000 and body["itc_all_other"]["cgst_paise"] == 900_000
    assert body["liability"]["cgst_paise"] == 1_350_000 and body["paid_by_credit"]["cgst_paise"] == 900_000
    assert body["paid_in_cash"]["cgst_paise"] == 450_000 and body["paid_in_cash"]["sgst_paise"] == 450_000
    assert body["counts"] == {"sales": 1, "purchases": 1, "reverse_charge": 0, "sales_without_invoice": 0}


def test_unused_credit_carries_to_the_next_month_and_can_be_put_right_by_hand(api, client_record):
    book(api, client_record, sale_tax=0)
    assert month(api, client_record)["carry_forward"]["cgst_paise"] == 900_000
    nov = month(api, client_record, "2025-11")
    assert nov["opening_credit"]["cgst_paise"] == 900_000 and nov["carry_forward"]["cgst_paise"] == 900_000
    assert enter(api, client_record, "2025-11", opening_credit_cgst_paise=500_000).status_code == 200
    assert month(api, client_record, "2025-11")["opening_credit"]["cgst_paise"] == 500_000


def test_igst_credit_pays_igst_then_cgst_and_cgst_credit_pays_igst_last(api, client_record):
    assert enter(api, client_record, opening_credit_igst_paise=1_000_000, opening_credit_cgst_paise=100_000).status_code == 200
    book(api, client_record, sale_tax=300_000)
    body = month(api, client_record)
    # CGST liability 300,000: CGST credit (100,000 + 900,000 from the purchase) covers it; the IGST credit is untouched.
    assert body["paid_by_credit"]["cgst_paise"] == 300_000 and body["carry_forward"]["igst_paise"] == 1_000_000


def test_reverse_charge_interest_and_late_fee_are_cash_and_reversed_credit_is_taken_off(api, client_record):
    book(api, client_record)
    done = enter(api, client_record, itc_reversed_cgst_paise=200_000, interest_cgst_paise=10_000, late_fee_paise=5_000, exempt_paise=700_000)
    assert done.status_code == 200, done.content
    body = done.json()
    assert body["itc_reversed"]["cgst_paise"] == 200_000 and body["paid_by_credit"]["cgst_paise"] == 700_000
    assert body["paid_in_cash"]["cgst_paise"] == 650_000 + 10_000 and body["late_fee_paise"] == 5_000
    assert body["exempt_nil_paise"] == 700_000


def test_sales_with_no_tax_are_flagged_until_entered_as_exempt_nil_or_zero_rated(api, client_record):
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    post_bill(api, client_record, voucher(customer, sales, kind="SALES", reference="S-9", cgst_paise=0, sgst_paise=0, heads=[{"ledger": sales["id"], "amount_paise": 2_000_000}]))
    body = month(api, client_record)
    assert body["outward_taxable"]["taxable_paise"] == 0 and body["untaxed_sales_paise"] == 2_000_000 and body["untaxed_unexplained_paise"] == 2_000_000
    explained = enter(api, client_record, zero_rated_paise=500_000, exempt_paise=1_500_000).json()
    assert explained["untaxed_unexplained_paise"] == 0


def test_a_bad_month_or_amount_is_refused_and_a_reader_cannot_enter(api, client_record, firm):
    from api.tests.conftest import member, sign_in
    from core.models import Role

    assert api.get(url(client_record), {"month": "2025-13"}).status_code == 400
    assert api.get(url(client_record)).status_code == 400
    assert enter(api, client_record, exempt_paise=-5).status_code == 400
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert reader.put(f"{url(client_record)}?month=2025-10", {}, format="json").status_code == 403
    assert reader.get(url(client_record), {"month": "2025-10"}).status_code in (200, 403)


def test_entering_figures_is_in_the_audit_trail(api, client_record):
    enter(api, client_record, exempt_paise=100)
    audit = api.get(f"{base(client_record)}/audit-trail/", {"kind": "SETTING"}).json()
    assert any("GSTR-3B entries for 2025-10" in row["label"] for row in audit["results"])


def test_cash_sales_booked_with_no_invoice_are_outward_supplies_too(api, client_record):
    """A month's cash sales as Tally keeps them: one sales voucher, Cash against Sales and the output tax, with no party and no bill."""
    import datetime

    from django.utils import timezone

    from classify.models import LedgerAccount, LedgerGroup
    from core.db.session import firm_context
    from ledger.models import Direction, JournalEntry, JournalLine, VoucherType

    with firm_context(client_record.firm_id):
        def ledger(name, group):
            return LedgerAccount.objects.get_or_create(firm_id=client_record.firm_id, client=client_record, name=name, defaults={"group": group})[0]

        cash, sales = ledger("Cash", LedgerGroup.CASH), ledger("Sales Gst 5%", LedgerGroup.SALES)
        cgst, sgst = ledger("OUTPUT CGST", LedgerGroup.DUTIES_AND_TAXES), ledger("OUTPUT SGST", LedgerGroup.DUTIES_AND_TAXES)
        entry = JournalEntry.objects.create(
            firm_id=client_record.firm_id, client=client_record, entry_no=1, financial_year=2025, entry_date=datetime.date(2025, 10, 31),
            voucher_type=VoucherType.SALES, approved_at=timezone.now(), narration="Cash sales for October",
        )
        JournalLine.objects.bulk_create([
            JournalLine.build(entry=entry, ledger_account=cash, direction=Direction.DEBIT, amount_paise=10_500_000),
            JournalLine.build(entry=entry, ledger_account=sales, direction=Direction.CREDIT, amount_paise=10_000_000),
            JournalLine.build(entry=entry, ledger_account=cgst, direction=Direction.CREDIT, amount_paise=250_000),
            JournalLine.build(entry=entry, ledger_account=sgst, direction=Direction.CREDIT, amount_paise=250_000),
        ])

    body = month(api, client_record)
    assert body["outward_taxable"]["taxable_paise"] == 10_000_000
    assert body["outward_taxable"]["cgst_paise"] == 250_000 and body["outward_taxable"]["sgst_paise"] == 250_000
    assert body["liability"]["cgst_paise"] == 250_000
    assert body["counts"]["sales_without_invoice"] == 1
