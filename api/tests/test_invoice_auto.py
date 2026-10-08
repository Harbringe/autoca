"""An invoice uploaded with no kind is told apart by the client's own GSTIN and booked when certain; otherwise it waits and says why."""

from __future__ import annotations

import io

import pytest

from api.tests.test_bills import base, make_ledger
from api.tests.test_invoices_api import SUPPLIER, TextPdfAdapter
from core.db.session import firm_context
from core.identifiers import gstin_check_character
from gst.models import GstRegistration
from integrations.registry import reset_adapter_cache

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
OWN = "27AAACA1234B1Z" + gstin_check_character("27AAACA1234B1Z")
CUSTOMER = "29AABCC9999D1Z" + gstin_check_character("29AABCC9999D1Z")


@pytest.fixture(autouse=True)
def text_pdfs(tmp_path, settings):
    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": f"{TextPdfAdapter.__module__}.TextPdfAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {**settings.INTEGRATION_OPTIONS, "pdf": {}, "storage": {"root": str(tmp_path / "storage")}}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def register_own_gstin(client_record):
    with firm_context(client_record.firm_id):
        registration = GstRegistration(firm_id=client_record.firm_id, client=client_record, state_code="27")
        registration.set_gstin(OWN)
        registration.save()


# The supplier prints their own GSTIN first and the buyer's after it.
PURCHASE = f"""RAVI TRADERS
TAX INVOICE
GSTIN: {SUPPLIER}
Bill to GSTIN: {OWN}
Invoice No: RT/900
Invoice Date: 12-08-2025
Taxable Value 10,000.00
CGST @ 9% 900.00
SGST @ 9% 900.00
Grand Total 11,800.00
"""

SALE = f"""ACME TRADERS
TAX INVOICE
GSTIN: {OWN}
Bill to GSTIN: {CUSTOMER}
Invoice No: AC/12
Invoice Date: 14-08-2025
Taxable Value 20,000.00
CGST @ 9% 1,800.00
SGST @ 9% 1,800.00
Grand Total 23,600.00
"""

NO_OWN = PURCHASE.replace(OWN, CUSTOMER)


def upload(api, client_record, text, name="inv.pdf"):
    file = io.BytesIO(b"%PDF-1.4\n" + text.encode())
    file.name = name
    return api.post(f"{base(client_record)}/invoices/upload/", {"file": file}, format="multipart")


def test_a_purchase_is_told_by_the_clients_gstin_as_buyer_and_booked(api, client_record):
    register_own_gstin(client_record)

    response = upload(api, client_record, PURCHASE)

    assert response.status_code == 201, response.content
    reading = response.json()
    assert reading["kind"] == "PURCHASE" and reading["status"] == "BOOKED"
    assert reading["auto_booked"] is True and reading["attention"] == "" and reading["bill"]
    bill = api.get(f"{base(client_record)}/bills/{reading['bill']}/").json()
    assert bill["kind"] == "PURCHASE" and bill["total_paise"] == 11_800_00 and bill["reference"] == "RT/900"
    parties = api.get(f"{base(client_record)}/parties/").json()["results"]
    assert [p["canonical_name"] for p in parties] == ["RAVI TRADERS"]


def test_a_sale_is_told_by_the_clients_gstin_as_issuer(api, client_record):
    register_own_gstin(client_record)
    # The page names who is billed; a text read does not, so the customer must exist already.
    api.post(f"{base(client_record)}/parties/", {"canonical_name": "Cee Retail", "role": "CUSTOMER", "gstin": CUSTOMER}, format="json")

    reading = upload(api, client_record, SALE).json()

    assert reading["kind"] == "SALES" and reading["status"] == "BOOKED" and reading["auto_booked"] is True


def test_without_the_clients_gstin_on_record_nothing_is_booked_and_it_says_why(api, client_record):
    reading = upload(api, client_record, PURCHASE).json()

    assert reading["kind"] == "" and reading["status"] == "OPEN" and reading["bill"] is None
    assert "own GSTIN is not on record" in reading["attention"]
    items = api.get(f"{base(client_record)}/open-items/", {"kind": "invoice_unbooked"}).json()["items"]
    assert len(items) == 1 and "own GSTIN is not on record" in items[0]["summary"]


def test_a_file_without_the_clients_gstin_is_not_guessed(api, client_record):
    register_own_gstin(client_record)

    reading = upload(api, client_record, NO_OWN).json()

    assert reading["kind"] == "" and reading["status"] == "OPEN"
    assert "None of the GSTINs" in reading["attention"]


def test_a_person_can_say_which_it_is_and_it_is_then_booked(api, client_record):
    reading = upload(api, client_record, PURCHASE).json()

    said = api.post(f"{base(client_record)}/invoices/{reading['id']}/kind/", {"kind": "PURCHASE"}, format="json")

    assert said.status_code == 200, said.content
    assert said.json()["kind"] == "PURCHASE" and said.json()["status"] == "BOOKED" and said.json()["auto_booked"] is True


def test_figures_that_do_not_add_up_are_not_booked(api, client_record):
    register_own_gstin(client_record)

    reading = upload(api, client_record, PURCHASE.replace("11,800.00", "11,900.00")).json()

    assert reading["status"] == "OPEN" and reading["bill"] is None and "do not add up" in reading["attention"]


def test_a_person_changes_an_auto_booked_bill_and_the_invoice_stays_with_it(api, client_record):
    register_own_gstin(client_record)
    reading = upload(api, client_record, PURCHASE).json()
    bill = api.get(f"{base(client_record)}/bills/{reading['bill']}/").json()
    purchases = make_ledger(api, client_record, "Raw Materials", "DIRECT_EXPENSE")
    body = {
        "kind": "PURCHASE", "party": bill["party"], "reference": "RT/900", "bill_date": "2025-08-12",
        "heads": [{"ledger": purchases["id"], "amount_paise": 10_000_00}],
        "cgst_paise": 900_00, "sgst_paise": 900_00,
    }

    changed = api.post(f"{base(client_record)}/bills/{bill['id']}/revise/", body, format="json")

    assert changed.status_code == 200, changed.content
    fresh = api.get(f"{base(client_record)}/invoices/{reading['id']}/").json()
    assert fresh["status"] == "BOOKED" and fresh["auto_booked"] is False and fresh["bill"] == changed.json()["id"]
    assert api.get(f"{base(client_record)}/bills/{bill['id']}/").status_code == 404


def test_naming_the_kind_at_upload_keeps_the_manual_flow(api, client_record):
    file = io.BytesIO(b"%PDF-1.4\n" + PURCHASE.encode())
    file.name = "inv.pdf"

    reading = api.post(f"{base(client_record)}/invoices/upload/", {"file": file, "kind": "PURCHASE"}, format="multipart").json()

    assert reading["status"] == "OPEN" and reading["auto_booked"] is False


def test_a_party_of_the_same_name_is_never_taken_over_by_what_a_file_says(api, client_record):
    register_own_gstin(client_record)
    api.post(f"{base(client_record)}/parties/", {"canonical_name": "Ravi Traders", "role": "VENDOR", "gstin": ""}, format="json")

    reading = upload(api, client_record, PURCHASE).json()

    assert reading["status"] == "OPEN" and reading["bill"] is None
    assert "already a party" in reading["attention"]
    parties = api.get(f"{base(client_record)}/parties/").json()["results"]
    assert [p["canonical_name"] for p in parties] == ["Ravi Traders"]


def test_a_sale_to_a_customer_not_on_record_waits_for_a_person(api, client_record):
    register_own_gstin(client_record)

    reading = upload(api, client_record, SALE).json()

    assert reading["kind"] == "SALES" and reading["status"] == "OPEN" and reading["bill"] is None
    assert "customer is not on record" in reading["attention"]


def _file(name, data):
    file = io.BytesIO(data)
    file.name = name
    return file


def test_a_word_invoice_is_read_and_booked_like_a_pdf(api, client_record):
    from integrations.tests.test_files import docx

    register_own_gstin(client_record)
    file = _file("invoice.docx", docx(PURCHASE.splitlines()))

    response = api.post(f"{base(client_record)}/invoices/upload/", {"file": file}, format="multipart")

    assert response.status_code == 201, response.content
    reading = response.json()
    assert reading["kind"] == "PURCHASE" and reading["status"] == "BOOKED" and reading["auto_booked"] is True


def test_an_excel_invoice_is_read_and_booked_like_a_pdf(api, client_record):
    from integrations.tests.test_files import workbook

    register_own_gstin(client_record)
    rows = [[line] for line in PURCHASE.splitlines()]
    file = _file("invoice.xlsx", workbook(rows))

    reading = api.post(f"{base(client_record)}/invoices/upload/", {"file": file}, format="multipart").json()

    assert reading["status"] == "BOOKED" and reading["auto_booked"] is True


def test_a_photo_of_an_invoice_is_kept_and_says_why_it_was_not_read_while_scans_are_off(api, client_record):
    from integrations.tests.test_files import png

    file = _file("photo.png", png())

    response = api.post(f"{base(client_record)}/invoices/upload/", {"file": file}, format="multipart")

    assert response.status_code == 201, response.content
    reading = response.json()
    assert reading["status"] == "OPEN" and reading["read"] is None and "not switched on" in reading["unreadable_reason"]


def test_a_file_of_a_kind_that_cannot_be_read_is_refused_in_words(api, client_record):
    file = _file("macro.exe", b"MZ\x90\x00 not an invoice")

    response = api.post(f"{base(client_record)}/invoices/upload/", {"file": file}, format="multipart")

    assert response.status_code == 400 and "cannot be read" in response.json()["fields"]["file"][0]


def test_a_draft_upload_is_read_but_never_booked_so_a_person_can_complete_it(api, client_record):
    register_own_gstin(client_record)
    file = _file("inv.pdf", b"%PDF-1.4\n" + PURCHASE.encode())

    reading = api.post(f"{base(client_record)}/invoices/upload/", {"file": file, "book": "false"}, format="multipart").json()

    assert reading["kind"] == "PURCHASE" and reading["status"] == "OPEN" and reading["bill"] is None
    assert reading["read"]["invoice_no"] == "RT/900"


def test_a_stored_invoice_can_be_shown_as_pages_in_the_viewer(api, client_record):
    from integrations.tests.test_files import docx

    file = _file("invoice.docx", docx(PURCHASE.splitlines()))
    reading = api.post(f"{base(client_record)}/invoices/upload/", {"file": file, "book": "false"}, format="multipart").json()

    info = api.get(f"/api/v1/documents/{reading['document']}/preview/")
    page = api.get(f"/api/v1/documents/{reading['document']}/preview/1/")

    assert info.status_code == 200 and info.json()["pages"] >= 1
    assert page.status_code == 200 and page["Content-Type"] == "image/png" and page.content.startswith(b"\x89PNG")
    assert api.get(f"/api/v1/documents/{reading['document']}/preview/99/").status_code == 404
