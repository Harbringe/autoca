"""An uploaded invoice shows the bank row that looks like its payment, so the two are not left as islands."""

from __future__ import annotations

import io

import pytest

from api.tests.test_bills import base, make_ledger, make_party
from api.tests.test_invoices_api import SUPPLIER, TextPdfAdapter
from api.tests.test_settlement_api import the_payment
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"

# Taxable 12,71,186.44 + CGST and SGST 1,14,406.78 each = 15,00,000.00, the statement's payment.
INVOICE = f"""RAVI TRADERS
TAX INVOICE
GSTIN: {SUPPLIER}
Invoice No: RT/777
Invoice Date: 20-07-2025
Taxable Value 12,71,186.44
CGST @ 9% 1,14,406.78
SGST @ 9% 1,14,406.78
Grand Total 15,00,000.00
"""


def upload_invoice(api, client_record, settings, text=INVOICE):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "pdf": f"{TextPdfAdapter.__module__}.TextPdfAdapter"}
    reset_adapter_cache()
    file = io.BytesIO(b"%PDF-1.4\n" + text.encode())
    file.name = "inv.pdf"
    return api.post(f"{base(client_record)}/invoices/upload/", {"file": file, "kind": "PURCHASE"}, format="multipart")


def pay_party(api, client_record):
    """The statement's payment, recorded as made to the supplier, and posted to an expense head."""
    row = the_payment(client_record)
    party = make_party(api, client_record, gstin=SUPPLIER)
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")
    api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": expense["id"], "party": party["id"], "learn": False}, format="json")
    posted = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")
    assert posted.status_code == 201, posted.content
    return posted.json()[0]["id"]


def test_a_payment_of_the_same_amount_to_that_party_is_shown_beside_the_invoice(api, client_record, statement, settings):
    entry = pay_party(api, client_record)

    reading = upload_invoice(api, client_record, settings).json()

    assert reading["proved"] is True
    (hint,) = reading["payments"]
    assert hint["posted_to"] == "Office Expenses" and hint["entry"] == entry and hint["on_party_account"] is False


def test_no_hint_when_the_amount_differs(api, client_record, statement, settings):
    pay_party(api, client_record)
    other = INVOICE.replace("12,71,186.44", "10,00,000.00").replace("1,14,406.78", "90,000.00").replace("15,00,000.00", "11,80,000.00")

    reading = upload_invoice(api, client_record, settings, other).json()

    assert reading["payments"] == []


def test_no_hint_when_the_party_is_not_known(api, client_record, statement, settings):
    reading = upload_invoice(api, client_record, settings).json()

    assert reading["suggested_party"] is None and reading["payments"] == []
