"""An uploaded invoice becomes a draft reading, and a person turns it into a bill, attaches it to one, or sets it aside."""

from __future__ import annotations

import io

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from core.identifiers import gstin_check_character
from integrations.pdf.base import PdfDocument, PdfPage, PdfTextAdapter
from integrations.registry import reset_adapter_cache

pytestmark = pytest.mark.django_db


class TextPdfAdapter(PdfTextAdapter):
    """Reads back the text a test wrote after the PDF signature, so invoices of any wording can be tried."""

    def __init__(self, **_ignored):
        pass

    def extract(self, data: bytes) -> PdfDocument:
        text = data.split(b"\n", 1)[1].decode() if b"\n" in data else ""
        return PdfDocument(engine="test", page_count=1, pages=(PdfPage(page_number=1, text=text),))


@pytest.fixture(autouse=True)
def text_pdfs(tmp_path, settings):
    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": f"{__name__}.TextPdfAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {**settings.INTEGRATION_OPTIONS, "pdf": {}, "storage": {"root": str(tmp_path / "storage")}}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


SUPPLIER = "27AABCR1234F1Z" + gstin_check_character("27AABCR1234F1Z")


def invoice_text(number="RT/042", total="11,800.00"):
    return f"""RAVI TRADERS
TAX INVOICE
GSTIN: {SUPPLIER}
Invoice No: {number}
Invoice Date: 12-08-2025
Taxable Value 10,000.00
CGST @ 9% 900.00
SGST @ 9% 900.00
Grand Total {total}
"""


def pdf(text: str) -> io.BytesIO:
    file = io.BytesIO(b"%PDF-1.4\n" + text.encode())
    file.name = "ravi-042.pdf"
    return file


def upload(api, client_record, text, kind="PURCHASE"):
    return api.post(f"{base(client_record)}/invoices/upload/", {"file": pdf(text), "kind": kind}, format="multipart")


def open_items(api, client_record, kind=None):
    params = {"kind": kind} if kind else {}
    return api.get(f"{base(client_record)}/open-items/", params).json()


def test_a_readable_invoice_becomes_a_proved_draft_and_an_open_item(api, client_record):
    response = upload(api, client_record, invoice_text())

    assert response.status_code == 201, response.content
    reading = response.json()
    assert reading["status"] == "OPEN" and reading["proved"] is True and reading["unreadable_reason"] == ""
    assert reading["read"]["invoice_no"] == "RT/042" and reading["read"]["invoice_date"] == "2025-08-12"
    assert reading["read"]["taxable_paise"] == 10_000_00 and reading["read"]["total_paise"] == 11_800_00
    assert reading["read"]["counterparty_gstin"] == SUPPLIER
    assert reading["suggested_party"] is None and reading["matching_bill"] is None
    waiting = open_items(api, client_record, "invoice_unbooked")["items"]
    assert len(waiting) == 1 and waiting[0]["link"] == {"type": "invoice", "id": reading["id"]}
    assert "waiting to be booked" in waiting[0]["summary"]


def test_an_invoice_that_does_not_add_up_is_listed_with_what_failed(api, client_record):
    reading = upload(api, client_record, invoice_text(total="11,900.00")).json()

    assert reading["proved"] is False
    assert [c["name"] for c in reading["checks"] if not c["ok"]] == ["arithmetic"]
    assert "does not add up" in open_items(api, client_record, "invoice_unbooked")["items"][0]["summary"]


def test_a_scan_is_kept_and_says_why_it_was_not_read(api, client_record):
    reading = upload(api, client_record, "").json()

    assert reading["read"] is None and "scan or a photo" in reading["unreadable_reason"]
    assert "could not be read" in open_items(api, client_record, "invoice_unbooked")["items"][0]["summary"]


def test_only_pdfs_are_taken(api, client_record):
    file = io.BytesIO(b"GIF89a not a pdf")
    file.name = "photo.pdf"

    response = api.post(f"{base(client_record)}/invoices/upload/", {"file": file, "kind": "PURCHASE"}, format="multipart")

    assert response.status_code == 400 and "file" in response.json()["fields"]


def test_the_same_file_again_returns_the_same_reading(api, client_record):
    first = upload(api, client_record, invoice_text()).json()
    again = upload(api, client_record, invoice_text())

    assert again.status_code == 200 and again.json()["id"] == first["id"]
    assert len(api.get(f"{base(client_record)}/invoices/").json()["results"]) == 1


def test_booking_it_with_the_file_attached_closes_the_reading_and_the_open_item(api, client_record):
    reading = upload(api, client_record, invoice_text()).json()
    party = make_party(api, client_record, gstin=SUPPLIER)
    purchases = make_ledger(api, client_record)
    body = voucher(
        party, purchases, reference="RT/042", bill_date="2025-08-12", cgst_paise=900_00, sgst_paise=900_00,
        heads=[{"ledger": purchases["id"], "amount_paise": 10_000_00}], document=reading["document"],
    )

    booked = post_bill(api, client_record, body)

    assert booked.status_code == 201, booked.content
    assert booked.json()["has_document"] is True
    after = api.get(f"{base(client_record)}/invoices/{reading['id']}/").json()
    assert after["status"] == "BOOKED" and after["bill"] == booked.json()["id"]
    assert open_items(api, client_record, "invoice_unbooked")["items"] == []
    assert open_items(api, client_record, "bill_without_document")["items"] == []


def test_the_party_with_that_gstin_is_suggested(api, client_record):
    make_party(api, client_record, gstin=SUPPLIER)

    reading = upload(api, client_record, invoice_text()).json()

    assert reading["suggested_party"]["name"] == "Ravi Traders"


def test_a_bill_booked_by_hand_first_is_found_and_the_file_is_attached_to_it(api, client_record):
    party = make_party(api, client_record, gstin=SUPPLIER)
    purchases = make_ledger(api, client_record)
    body = voucher(
        party, purchases, reference="RT/042", bill_date="2025-08-12", cgst_paise=900_00, sgst_paise=900_00,
        heads=[{"ledger": purchases["id"], "amount_paise": 10_000_00}],
    )
    bill = post_bill(api, client_record, body).json()
    assert [i["kind"] for i in open_items(api, client_record)["items"]] == ["bill_without_document"]

    reading = upload(api, client_record, invoice_text()).json()
    assert reading["matching_bill"]["id"] == bill["id"]
    attached = api.post(f"{base(client_record)}/invoices/{reading['id']}/attach/", {"bill": bill["id"]}, format="json")

    assert attached.status_code == 200, attached.content
    assert attached.json()["status"] == "ATTACHED" and attached.json()["bill"] == bill["id"]
    assert open_items(api, client_record)["items"] == []
    shown = api.get(f"{base(client_record)}/bills/{bill['id']}/").json()
    assert shown["has_document"] is True


def test_a_bill_cannot_be_given_two_files(api, client_record):
    party = make_party(api, client_record, gstin=SUPPLIER)
    purchases = make_ledger(api, client_record)
    body = voucher(party, purchases, reference="RT/042", heads=[{"ledger": purchases["id"], "amount_paise": 10_000_00}])
    bill = post_bill(api, client_record, body).json()
    one = upload(api, client_record, invoice_text()).json()
    two = upload(api, client_record, invoice_text(number="RT/043")).json()

    api.post(f"{base(client_record)}/invoices/{one['id']}/attach/", {"bill": bill["id"]}, format="json")
    second = api.post(f"{base(client_record)}/invoices/{two['id']}/attach/", {"bill": bill["id"]}, format="json")

    assert second.status_code == 422 and "already has an invoice file" in second.json()["detail"]


def test_setting_an_invoice_aside_removes_it_from_the_open_items(api, client_record):
    reading = upload(api, client_record, invoice_text()).json()

    done = api.post(f"{base(client_record)}/invoices/{reading['id']}/discard/", format="json")

    assert done.status_code == 200 and done.json()["status"] == "DISCARDED"
    assert open_items(api, client_record, "invoice_unbooked")["items"] == []
    again = api.post(f"{base(client_record)}/invoices/{reading['id']}/discard/", format="json")
    assert again.status_code == 422


def test_a_read_only_member_may_read_but_not_upload_or_decide(client_record, api, reader):
    reading = upload(api, client_record, invoice_text()).json()
    viewer = sign_in(reader.user)

    assert viewer.get(f"{base(client_record)}/invoices/").status_code == 200
    assert upload(viewer, client_record, invoice_text(number="X-1")).status_code == 403
    assert viewer.post(f"{base(client_record)}/invoices/{reading['id']}/discard/", format="json").status_code == 403
