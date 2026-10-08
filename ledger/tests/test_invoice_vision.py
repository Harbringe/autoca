"""A scanned invoice is copied by the model and proved by the same arithmetic as a text one; nothing it says is trusted."""

from __future__ import annotations

import datetime
import json

import pytest

from core.identifiers import gstin_check_character
from integrations.llm.base import LLMResponse, LLMUnavailable
from ledger import invoice_vision
from ledger.invoice_reader import reading_from_fields

SUPPLIER = "27AABCR1234F1Z" + gstin_check_character("27AABCR1234F1Z")
BUYER = "29AAACA1234B1Z" + gstin_check_character("29AAACA1234B1Z")

GOOD = {
    "supplier_name": "Ravi Traders", "supplier_gstin": SUPPLIER, "buyer_name": "Acme Traders", "buyer_gstin": BUYER,
    "invoice_no": "RT/42", "invoice_date": "12-08-2025", "taxable": "₹10,000.00",
    "cgst": "900.00", "sgst": "900.00", "igst": "", "cess": "", "round_off": "", "total": "11,800.00",
}


class Llm:
    def __init__(self, reply):
        self.reply = reply

    def complete_json_with_images(self, system, user, images, *, max_tokens):
        if isinstance(self.reply, Exception):
            raise self.reply
        return LLMResponse(text=json.dumps(self.reply), model="m")


@pytest.fixture(autouse=True)
def no_render(monkeypatch):
    monkeypatch.setattr(invoice_vision, "render_pages", lambda data: [b"png"])
    monkeypatch.setattr(invoice_vision, "record", lambda **kw: None)


def test_a_good_copy_proves_and_keeps_who_is_who():
    reading = reading_from_fields(GOOD)

    assert reading.proved
    assert (reading.supplier_gstin, reading.buyer_gstin) == (SUPPLIER, BUYER)
    assert reading.total_paise == 11_800_00 and reading.buyer_name == "Acme Traders"


def test_a_misread_digit_breaks_the_arithmetic_and_is_not_proved():
    reading = reading_from_fields({**GOOD, "total": "11,300.00"})

    assert not reading.proved and [c.name for c in reading.failed] == ["arithmetic"]


def test_a_gstin_that_fails_its_check_character_is_dropped():
    reading = reading_from_fields({**GOOD, "buyer_gstin": BUYER[:-1] + ("A" if BUYER[-1] != "A" else "B")})

    assert reading.buyer_gstin == "" and reading.gstins == [SUPPLIER]


def test_the_model_reply_is_read_through_the_same_proof():
    reading = invoice_vision.read_scanned_invoice(b"%PDF", 1, Llm(GOOD))

    assert reading.proved and reading.invoice_no == "RT/42"


def test_an_unavailable_model_says_so_in_words():
    with pytest.raises(invoice_vision.InvoiceVisionError, match="not set up"):
        invoice_vision.read_scanned_invoice(b"%PDF", 1, Llm(LLMUnavailable("none")))


def test_amounts_as_json_numbers_and_an_iso_date_are_read_exactly():
    fields = {
        **GOOD, "invoice_date": "2025-08-12", "taxable": 47143.0, "cgst": 1178.58, "sgst": 1178.58, "igst": None,
        "cess": None, "round_off": -0.16, "total": 49500.0, "unsure": ["invoice_date", 5],
    }

    reading = reading_from_fields(fields)

    assert reading.taxable_paise == 47_143_00 and reading.cgst_paise == 1_178_58 and reading.round_off_paise == -16
    assert reading.invoice_date == datetime.date(2025, 8, 12) and reading.proved
    assert reading.unsure == ["invoice_date"]


def test_the_prompt_asks_for_plain_numbers_iso_dates_and_the_fields_it_doubts():
    text = invoice_vision.INSTRUCTION

    assert "JSON NUMBER" in text and "YYYY-MM-DD" in text and '"unsure"' in text and "(-)0.16" in text
