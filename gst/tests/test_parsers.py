"""Reading GSTR-2B and the register. Refusals matter as much as reads."""

import datetime
import io
import json

import pytest

from gst.matching import Section
from gst.parsers import GstParseError, parse_gstr2b_json, parse_register

G = "27AAAPL1234C1Z5"


def portal(**over):
    doc = {
        "gstin": "29ABCDE1234F1Z5",
        "rtnprd": "082026",
        "docdata": {
            "b2b": [
                {
                    "ctin": G,
                    "trdnm": "Acme Traders",
                    "inv": [
                        {"inum": "INV-1", "dt": "12-08-2026", "txval": 10000.5, "igst": 0,
                         "cgst": 900.05, "sgst": 900.05, "cess": 0, "rev": "N"},
                        {"inum": "INV-2", "dt": "15-08-2026", "rev": "Y", "items": [
                            {"txval": 100, "igst": 18}, {"txval": 50, "igst": 9}]},
                    ],
                }
            ],
            "cdnr": [{"ctin": G, "nt": [{"ntnum": "CN-1", "dt": "20-08-2026",
                                         "txval": 100, "cgst": 9, "sgst": 9}]}],
        },
    }
    doc["docdata"].update(over)
    return json.dumps({"data": doc}).encode()


def test_portal_json_reads_amounts_exactly_and_the_period():
    p = parse_gstr2b_json(portal())
    assert p.period_start == datetime.date(2026, 8, 1)
    a, b, cn = p.invoices
    assert (a.taxable_paise, a.cgst_paise) == (1000050, 90005)  # no float drift
    assert b.igst_paise == 2700 and b.rcm  # itemised, summed
    assert cn.section is Section.CDN and a.gstin == G and a.supplier_name == "Acme Traders"


def test_portal_json_refuses_other_json():
    with pytest.raises(GstParseError):
        parse_gstr2b_json(b'{"hello": 1}')
    with pytest.raises(GstParseError):
        parse_gstr2b_json(b"not json")


def csv_bytes(text):
    return text.encode()


def test_register_csv_with_title_rows_and_lakh_commas():
    text = (
        "Purchase Register,,,,,\n"
        "Acme Ltd,,,,,\n"
        "Supplier GSTIN,Bill No,Bill Date,Taxable Value,CGST,SGST,HSN,Ledger,RCM\n"
        f'{G},INV/0001,12-08-2026,"1,00,000.00","9,000.00","9,000.00",4820,Stationery,No\n'
        f",X9,13/08/2026,500,0,0,,Freight (GTA),Yes\n"
        ",,,,,,,,\n"
    )
    a, b = parse_register(csv_bytes(text), "reg.csv")
    assert a.taxable_paise == 10_000_000 and a.cgst_paise == 900_000
    assert a.invoice_date == datetime.date(2026, 8, 12) and a.hsn == "4820"
    assert not a.rcm and b.rcm and b.gstin == ""


def test_register_xlsx():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["GSTIN", "Invoice Number", "Invoice Date", "Taxable Value", "IGST"])
    ws.append([G, "A-1", datetime.date(2026, 8, 3), 1234.5, 222.21])
    buf = io.BytesIO()
    wb.save(buf)
    (inv,) = parse_register(buf.getvalue(), "reg.xlsx")
    assert inv.taxable_paise == 123450 and inv.igst_paise == 22221


def test_register_refuses_unreadable_amount_with_the_row():
    text = "GSTIN,Invoice No,Taxable Value,CGST\n" + f"{G},1,abc,0\n"
    with pytest.raises(GstParseError, match="row 2"):
        parse_register(csv_bytes(text), "r.csv")


def test_register_refuses_without_headers_or_tax_columns():
    with pytest.raises(GstParseError):
        parse_register(b"a,b\n1,2\n", "r.csv")
    with pytest.raises(GstParseError, match="tax columns"):
        parse_register(b"GSTIN,Invoice No\nX,1\n", "r.csv")
    with pytest.raises(GstParseError):
        parse_register(b"x", "r.pdf")


def test_column_mapping_override():
    text = "Vendor GST,Ref,Amt,CGST\n" f"{G},9,100,9\n"
    (inv,) = parse_register(
        csv_bytes(text), "r.csv", mapping={"gstin": "Vendor GST", "invoice_no": "Ref", "taxable": "Amt"}
    )
    assert inv.invoice_no == "9" and inv.gstin == G and inv.taxable_paise == 10000
