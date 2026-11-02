"""Reading Tally's stock-item export: name, unit, HSN, GST rate, and the opening quantity and value.

Synthetic files shaped like Tally's ``STOCKITEM`` master. Like the other masters readers this is UNVERIFIED against a real export.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from ledger.tally_parse import TallyParseError, TallyTooLargeError
from ledger.tally_stock import StockRow, read_stock_items

LIMIT = 10 * 1024 * 1024


def xml(*items: str) -> bytes:
    body = "".join(f"<TALLYMESSAGE>{i}</TALLYMESSAGE>" for i in items)
    return f"<ENVELOPE><BODY><IMPORTDATA><REQUESTDATA>{body}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>".encode()


MUSTARD = (
    '<STOCKITEM NAME="Mustard Oil 1L"><PARENT>Oils</PARENT><BASEUNITS>Nos</BASEUNITS>'
    "<OPENINGBALANCE> 40 Nos</OPENINGBALANCE><OPENINGVALUE>-4000.00</OPENINGVALUE>"
    "<GSTDETAILS.LIST><HSNCODE>1514</HSNCODE><STATEWISEDETAILS.LIST><RATEDETAILS.LIST>"
    "<GSTRATEDUTYHEAD>Central Tax</GSTRATEDUTYHEAD><GSTRATE> 2.5</GSTRATE></RATEDETAILS.LIST>"
    "<RATEDETAILS.LIST><GSTRATEDUTYHEAD>State Tax</GSTRATEDUTYHEAD><GSTRATE> 2.5</GSTRATE></RATEDETAILS.LIST>"
    "<RATEDETAILS.LIST><GSTRATEDUTYHEAD>Integrated Tax</GSTRATEDUTYHEAD><GSTRATE> 5</GSTRATE></RATEDETAILS.LIST>"
    "</STATEWISEDETAILS.LIST></GSTDETAILS.LIST></STOCKITEM>"
)


def test_an_item_is_read_with_its_unit_hsn_rate_and_opening_stock():
    (row,) = read_stock_items(xml(MUSTARD), "items.xml", max_bytes=LIMIT)
    assert row == StockRow(name="Mustard Oil 1L", unit="Nos", hsn_sac="1514", gst_rate=Decimal("5"), opening_qty=Decimal("40"), opening_value_paise=4_000_00)


def test_the_gst_rate_is_the_integrated_rate_or_the_two_halves_added():
    halves = MUSTARD.replace("<RATEDETAILS.LIST><GSTRATEDUTYHEAD>Integrated Tax</GSTRATEDUTYHEAD><GSTRATE> 5</GSTRATE></RATEDETAILS.LIST>", "")
    (row,) = read_stock_items(xml(halves), "items.xml", max_bytes=LIMIT)
    assert row.gst_rate == Decimal("5.0")


def test_an_item_with_nothing_but_a_name_is_still_an_item():
    (row,) = read_stock_items(xml('<STOCKITEM NAME="Gift wrap"></STOCKITEM>'), "items.xml", max_bytes=LIMIT)
    assert (row.name, row.unit, row.hsn_sac, row.gst_rate, row.opening_qty, row.opening_value_paise) == ("Gift wrap", "", "", None, Decimal(0), 0)


def test_an_opening_balance_in_a_compound_unit_keeps_the_first_quantity():
    item = '<STOCKITEM NAME="Tiles"><BASEUNITS>Box</BASEUNITS><OPENINGBALANCE>12.500 Box = 150 Nos</OPENINGBALANCE><OPENINGVALUE>-2500</OPENINGVALUE></STOCKITEM>'
    (row,) = read_stock_items(xml(item), "items.xml", max_bytes=LIMIT)
    assert row.opening_qty == Decimal("12.5") and row.opening_value_paise == 2_500_00


def test_several_items_come_back_in_file_order_and_the_same_name_twice_is_read_once():
    rows = read_stock_items(xml(MUSTARD, '<STOCKITEM NAME="Rice"></STOCKITEM>', '<STOCKITEM NAME="mustard oil 1l"></STOCKITEM>'), "items.xml", max_bytes=LIMIT)
    assert [r.name for r in rows] == ["Mustard Oil 1L", "Rice"]


def test_a_json_export_is_read_the_same_way():
    doc = {"tallymessage": [{"metadata": {"type": "Stock Item", "name": "Rice"}, "baseunits": "Kg", "openingbalance": "10 Kg", "openingvalue": "-500.00"}]}
    (row,) = read_stock_items(json.dumps(doc).encode(), "items.json", max_bytes=LIMIT)
    assert (row.name, row.unit, row.opening_qty, row.opening_value_paise) == ("Rice", "Kg", Decimal("10"), 500_00)


@pytest.mark.parametrize("data,name", [(b"not a file", "items.xml"), (xml("<LEDGER NAME='Cash'></LEDGER>"), "items.xml"), (b"{}", "items.json"), (b"x", "items.pdf")])
def test_what_is_not_a_stock_item_export_is_refused_in_words(data, name):
    with pytest.raises(TallyParseError):
        read_stock_items(data, name, max_bytes=LIMIT)


def test_a_file_that_is_too_large_is_refused():
    with pytest.raises(TallyTooLargeError):
        read_stock_items(b"x" * 100, "items.xml", max_bytes=10)


def test_an_xml_bomb_is_refused_not_expanded():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><ENVELOPE><STOCKITEM NAME="&b;"/></ENVELOPE>'
    with pytest.raises(TallyParseError):
        read_stock_items(bomb, "items.xml", max_bytes=LIMIT)
