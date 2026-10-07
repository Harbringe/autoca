"""An invoice that arrives after its payment was held as an advance takes that payment; a flagged party is not booked blind."""

from __future__ import annotations

import io

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from api.tests.test_invoice_auto import OWN, register_own_gstin
from api.tests.test_invoices_api import SUPPLIER, TextPdfAdapter
from api.tests.test_settlement_api import approvals, place, the_payment
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"

# Taxable 12,71,186.44 + CGST and SGST 1,14,406.78 each = 15,00,000.00, the statement's payment.
INVOICE = f"""RAVI TRADERS
TAX INVOICE
GSTIN: {SUPPLIER}
Bill to GSTIN: {OWN}
Invoice No: RT/777
Invoice Date: 20-07-2025
Taxable Value 12,71,186.44
CGST @ 9% 1,14,406.78
SGST @ 9% 1,14,406.78
Grand Total 15,00,000.00
"""


def upload(api, client_record, settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "pdf": f"{TextPdfAdapter.__module__}.TextPdfAdapter"}
    reset_adapter_cache()
    file = io.BytesIO(b"%PDF-1.4\n" + INVOICE.encode())
    file.name = "inv.pdf"
    return api.post(f"{base(client_record)}/invoices/upload/", {"file": file}, format="multipart")


def hold_the_payment_as_an_advance(api, client_record):
    row = the_payment(client_record)
    party = make_party(api, client_record, gstin=SUPPLIER)
    purchases = make_ledger(api, client_record)
    earlier = voucher(
        party, purchases, reference="EARLIER", cgst_paise=0, sgst_paise=0,
        heads=[{"ledger": purchases["id"], "amount_paise": 1_00_000}],
    )
    post_bill(api, client_record, earlier)
    party = api.get(f"{base(client_record)}/parties/{party['id']}/").json()
    place(api, row, party["ledger"])
    done = approvals(
        api, client_record,
        {"classifications": [str(row.pk)], "settlements": [{"classification": str(row.pk), "remainder": "ADVANCE", "allocations": []}]},
    )
    assert done.status_code == 201, done.content
    return party


def test_money_held_as_an_advance_is_applied_when_its_invoice_arrives(api, client_record, statement, settings):
    register_own_gstin(client_record)
    hold_the_payment_as_an_advance(api, client_record)

    reading = upload(api, client_record, settings).json()

    assert reading["status"] == "BOOKED" and reading["auto_booked"] is True, reading
    bill = api.get(f"{base(client_record)}/bills/{reading['bill']}/").json()
    assert bill["open_paise"] == 0 and [a["amount_paise"] for a in bill["allocations"]] == [15_00_000_00]


def test_a_party_that_normally_has_tds_deducted_is_not_booked_blind(api, client_record, statement, settings):
    register_own_gstin(client_record)
    party = make_party(api, client_record, gstin=SUPPLIER)
    api.patch(f"{base(client_record)}/parties/{party['id']}/", {"tds_section": "194C"}, format="json")

    reading = upload(api, client_record, settings).json()

    assert reading["status"] == "OPEN" and reading["bill"] is None
    assert "TDS" in reading["attention"] and "194C" in reading["attention"]


def test_a_party_under_reverse_charge_is_not_booked_blind(api, client_record, statement, settings):
    register_own_gstin(client_record)
    party = make_party(api, client_record, gstin=SUPPLIER)
    api.patch(f"{base(client_record)}/parties/{party['id']}/", {"rcm_default": True}, format="json")

    reading = upload(api, client_record, settings).json()

    assert reading["status"] == "OPEN" and "Reverse charge" in reading["attention"]
