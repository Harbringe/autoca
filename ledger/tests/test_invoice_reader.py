"""Reading an invoice's text and proving it. Pure: no database."""

from __future__ import annotations

import datetime

import pytest

from core.identifiers import gstin_check_character
from ledger.invoice_reader import read_invoice

TODAY = datetime.date(2026, 10, 6)


def gstin(first_fourteen: str) -> str:
    return first_fourteen + gstin_check_character(first_fourteen)


SUPPLIER = gstin("27AABCR1234F1Z")
BUYER = gstin("27AAACK5678L1Z")

INTRA_STATE = f"""
RAVI TRADERS
TAX INVOICE
GSTIN: {SUPPLIER}
Invoice No: RT/2025-26/0042
Invoice Date: 12-08-2025
Bill To: Kiran Stores   GSTIN: {BUYER}
Description        HSN   Qty   Rate     Amount
Stationery         4820   10   1000.00  10,000.00
Taxable Value                           10,000.00
CGST @ 9%                                  900.00
SGST @ 9%                                  900.00
Round Off                                    0.00
Grand Total                             11,800.00
"""


def read(text):
    return read_invoice(text, today=TODAY)


def test_an_intra_state_invoice_is_read_and_proved():
    reading = read(INTRA_STATE)

    assert reading.supplier_name == "RAVI TRADERS"
    assert reading.gstins == [SUPPLIER, BUYER]
    assert reading.invoice_no == "RT/2025-26/0042"
    assert reading.invoice_date == datetime.date(2025, 8, 12)
    assert (reading.taxable_paise, reading.cgst_paise, reading.sgst_paise, reading.igst_paise) == (10_000_00, 900_00, 900_00, 0)
    assert reading.total_paise == 11_800_00
    assert reading.proved, reading.failed


def test_an_inter_state_invoice_with_round_off_is_proved():
    text = f"""
    Sharma Metals Pvt Ltd
    Invoice No. SM-77
    Dated 03/09/2025
    GSTIN {SUPPLIER}
    Sub Total 4,999.50
    IGST @ 18% 899.91
    Round off (-) 0.41
    Total Invoice Value Rs. 5,899.00
    """.replace("(-) 0.41", "-0.41")
    reading = read(text)

    assert reading.igst_paise == 899_91 and reading.cgst_paise == 0
    assert reading.round_off_paise == -41
    assert reading.total_paise == 5_899_00
    assert reading.proved, reading.failed


def test_a_tax_summary_printed_twice_does_not_double_count():
    text = INTRA_STATE + """
    HSN Summary
    4820   Taxable 10,000.00   CGST 900.00   SGST 900.00
    """
    reading = read(text)

    assert reading.cgst_paise == 900_00 and reading.sgst_paise == 900_00
    assert reading.proved, reading.failed


def test_an_invoice_that_does_not_add_up_is_not_proved_and_says_why():
    text = INTRA_STATE.replace("Grand Total                             11,800.00", "Grand Total                             11,900.00")

    reading = read(text)

    assert not reading.proved
    assert [c.name for c in reading.failed] == ["arithmetic"]
    assert "than the total" in reading.failed[0].detail


def test_igst_together_with_cgst_is_refused():
    text = INTRA_STATE.replace("Round Off", "IGST @ 18%   1,800.00\nRound Off").replace("11,800.00", "13,600.00")

    assert not read(text).proved


@pytest.mark.parametrize("missing", ["Invoice No: RT/2025-26/0042", "Invoice Date: 12-08-2025"])
def test_a_missing_number_or_date_is_flagged(missing):
    reading = read(INTRA_STATE.replace(missing, ""))

    assert not reading.proved
    assert {"invoice_no", "invoice_date"} & {c.name for c in reading.failed}


def test_a_gstin_with_a_wrong_check_character_is_not_taken():
    bad = SUPPLIER[:-1] + ("A" if SUPPLIER[-1] != "A" else "B")
    reading = read(INTRA_STATE.replace(SUPPLIER, bad))

    assert bad not in reading.gstins and reading.gstins == [BUYER]


def test_a_future_or_pre_gst_date_is_not_plausible():
    assert "invoice_date" in [c.name for c in read(INTRA_STATE.replace("12-08-2025", "12-08-2031")).failed]
    assert "invoice_date" in [c.name for c in read(INTRA_STATE.replace("12-08-2025", "12-08-2012")).failed]


def test_text_with_no_amounts_is_not_proved():
    reading = read("Some letter\nDear sir, please find enclosed.")

    assert not reading.proved and "amounts_found" in [c.name for c in reading.failed]


def test_a_text_month_date_is_read():
    reading = read(INTRA_STATE.replace("12-08-2025", "12 Aug 2025"))

    assert reading.invoice_date == datetime.date(2025, 8, 12)


def test_a_round_off_printed_with_its_minus_apart_from_the_figure_is_read_with_its_sign():
    """Some invoices print ``(-)0.16``; reading that as nothing made a good invoice look wrong by 16 paise."""
    from ledger.invoice_reader import _paise, reading_from_fields

    for text in ("(-)0.16", "-0.16", "(0.16)", "−0.16"):
        assert _paise(text) == -16
    assert _paise("Rs. 49500") == 4_950_000
    gstin = "27ABTPN5133F1ZF"
    fields = {
        "supplier_name": "Gajraj Trading Company", "supplier_gstin": gstin, "buyer_gstin": "", "invoice_no": "GTC 24/25 512",
        "invoice_date": "01-08-2025", "taxable": "47,143.00", "cgst": "1,178.58", "sgst": "1,178.58",
        "round_off": "(-)0.16", "total": "49,500.00",
    }
    from core.identifiers import gstin_check_character

    fields["supplier_gstin"] = "27ABTPN5133F1Z" + gstin_check_character("27ABTPN5133F1Z")

    reading = reading_from_fields(fields)

    assert reading.round_off_paise == -16 and reading.proved


def test_when_the_figures_are_a_few_paise_out_it_says_by_how_much_and_suggests_round_off():
    from core.identifiers import gstin_check_character
    from ledger.invoice_reader import reading_from_fields

    fields = {
        "supplier_gstin": "27ABTPN5133F1Z" + gstin_check_character("27ABTPN5133F1Z"), "invoice_no": "A/1",
        "invoice_date": "01-08-2025", "taxable": "47,143.00", "cgst": "1,178.58", "sgst": "1,178.58", "total": "49,500.00",
    }

    reading = reading_from_fields(fields)

    assert not reading.proved
    assert "0.16 more than the total" in reading.failed[0].detail and "Round off" in reading.failed[0].detail
