"""Reading a Tally vouchers export: shape, signs, and what is refused."""

from __future__ import annotations

import datetime

import pytest

from ledger.tally_parse import TallyParseError, TallyTooLargeError
from ledger.tally_vouchers import parse_vouchers
from ledger.tests.tally_voucher_xml import line, voucher, vouchers_xml

MAX = 10 * 1024 * 1024


def sale(guid="g1", number="1", date="20250401", amount=1180.0):
    return voucher(
        guid=guid, vtype="Sales", number=number, date=date, party="Acme Traders", gstin="27ABCDE1234F1Z5",
        lines=[line("Acme Traders", amount, party=True), line("Sales", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)],
    )


def test_reads_a_sales_voucher_with_the_books_sign():
    parsed = parse_vouchers(vouchers_xml([sale()]), "sales.xml", max_bytes=MAX)
    assert len(parsed.vouchers) == 1
    v = parsed.vouchers[0]
    assert (v.guid, v.tally_type, v.number, v.date) == ("g1", "Sales", "1", datetime.date(2025, 4, 1))
    assert v.party == "Acme Traders" and v.party_gstin == "27ABCDE1234F1Z5"
    assert [(ln.ledger, ln.signed_paise, ln.is_party) for ln in v.lines] == [
        ("Acme Traders", 118000, True), ("Sales", -100000, False), ("Output CGST", -9000, False), ("Output SGST", -9000, False),
    ]
    assert parsed.company == "TEST CO" and parsed.date_from == parsed.date_to == datetime.date(2025, 4, 1)


def _json_export(*messages):
    import json

    return json.dumps({"tallymessage": list(messages)}).encode("utf-8")


def _json_sale(guid="g1", **over):
    """Shaped after Tally's own JSON export: lower-case keys, real booleans, a list of objects for each repeated block."""
    v = {
        "metadata": {"type": "Voucher", "vchtype": "GST SALE", "action": "Create", "objview": "Invoice Voucher View"},
        "date": "20250401", "guid": guid, "vouchertypename": "GST SALE", "vouchernumber": "7", "partyledgername": "Acme Traders",
        "partygstin": "27ABCDE1234F1Z5", "cmpgstin": "27AAACX1234A1Z9", "reference": "REF-7", "narration": "April sale",
        "isdeleted": False, "iscancelled": False, "isoptional": False,
        "oldauditentryids": [{"metadata": True, "type": "Number"}, "-1"],
        "allledgerentries": [
            {"ledgername": "Acme Traders", "ispartyledger": True, "amount": "-1180.00",
             "billallocations": [{"name": "INV-7", "billtype": "New Ref", "amount": "-1180.00"}]},
            {"ledgername": "Output CGST", "ispartyledger": False, "amount": "90.00"},
            {"ledgername": "Output SGST", "ispartyledger": False, "amount": "90.00"},
        ],
        "allinventoryentries": [
            {"stockitemname": "Widget", "billedqty": " 10 Nos", "amount": "1000.00",
             "accountingallocations": [{"ledgername": "Sales", "amount": "1000.00"}]},
        ],
    }
    v.update(over)
    return v


def test_a_json_export_reads_like_the_same_voucher_in_xml():
    parsed = parse_vouchers(_json_export(_json_sale()), "sales.json", max_bytes=MAX)
    assert len(parsed.vouchers) == 1 and parsed.skipped == []
    v = parsed.vouchers[0]
    assert (v.guid, v.tally_type, v.number, v.date) == ("g1", "GST SALE", "7", datetime.date(2025, 4, 1))
    assert (v.party, v.party_gstin, v.own_gstin, v.reference, v.narration) == (
        "Acme Traders", "27ABCDE1234F1Z5", "27AAACX1234A1Z9", "REF-7", "April sale",
    )
    assert [(ln.ledger, ln.signed_paise, ln.is_party) for ln in v.lines] == [
        ("Acme Traders", 118000, True), ("Output CGST", -9000, False), ("Output SGST", -9000, False), ("Sales", -100000, False),
    ]
    assert v.lines[0].bills == (("INV-7", "New Ref", 118000),)
    assert [(i.name, i.quantity, i.unit, i.value_paise) for i in v.items] == [("Widget", "10", "Nos", 100000)]


def test_json_vouchers_that_tally_deleted_cancelled_or_left_optional_are_skipped_with_a_reason():
    parsed = parse_vouchers(
        _json_export(_json_sale("a"), _json_sale("b", iscancelled=True), _json_sale("c", isoptional=True), _json_sale("d", isdeleted=True)),
        "v.json", max_bytes=MAX,
    )
    assert [v.guid for v in parsed.vouchers] == ["a"]
    assert {s.reason.split(" ")[0] for s in parsed.skipped} == {"Cancelled", "Optional", "Deleted"}


def test_a_json_file_that_is_not_a_vouchers_export_is_refused_in_plain_words():
    for body in (b"not json at all", b'{"other": []}', b"[1, 2]", b'{"tallymessage": "x"}'):
        with pytest.raises(TallyParseError):
            parse_vouchers(body, "v.json", max_bytes=MAX)
    with pytest.raises(TallyParseError, match="No vouchers"):
        parse_vouchers(_json_export({"metadata": {"type": "Ledger"}}), "v.json", max_bytes=MAX)


def test_json_with_nan_or_absurd_nesting_is_refused_not_a_crash():
    with pytest.raises(TallyParseError):
        parse_vouchers(b'{"tallymessage": [NaN]}', "v.json", max_bytes=MAX)
    deep = b'{"tallymessage": [{"metadata": {"type": "Voucher"}, "x": ' + b'{"a": ' * 200 + b"1" + b"}" * 200 + b"}]}"
    with pytest.raises(TallyParseError):
        parse_vouchers(deep, "v.json", max_bytes=MAX)


def test_a_vouchers_file_of_another_kind_is_refused_naming_both_formats():
    with pytest.raises(TallyParseError, match=r"\.xml.*\.json"):
        parse_vouchers(b"x", "v.txt", max_bytes=MAX)


def test_cancelled_and_optional_vouchers_are_skipped_with_a_reason():
    xml = vouchers_xml([sale("a"), voucher(guid="b", vtype="Sales", number="2", date="20250402", lines=[], cancelled=True),
                        voucher(guid="c", vtype="Journal", number="3", date="20250403", lines=[], optional=True)])
    parsed = parse_vouchers(xml, "v.xml", max_bytes=MAX)
    assert [v.guid for v in parsed.vouchers] == ["a"]
    assert {s.reason.split(" ")[0] for s in parsed.skipped} == {"Cancelled", "Optional"}


def test_a_voucher_with_a_bad_date_or_no_guid_is_skipped_not_fatal():
    xml = vouchers_xml([sale("a"), sale("", number="9"), sale("z", date="20251345")])
    parsed = parse_vouchers(xml, "v.xml", max_bytes=MAX)
    assert [v.guid for v in parsed.vouchers] == ["a"]
    assert len(parsed.skipped) == 2


def test_two_roots_are_not_well_formed():
    one = vouchers_xml([sale("a")], company="ONE")
    two = vouchers_xml([sale("b")], company="TWO")
    with pytest.raises(TallyParseError):
        parse_vouchers(one + two, "v.xml", max_bytes=MAX)


def test_two_companies_are_recorded_so_the_import_can_refuse():
    data = vouchers_xml([sale()], company="ONE").replace(
        b"</STATICVARIABLES>", b"<SVCURRENTCOMPANY>TWO</SVCURRENTCOMPANY></STATICVARIABLES>"
    )
    assert parse_vouchers(data, "v.xml", max_bytes=MAX).companies == {"ONE", "TWO"}


def test_a_doctype_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>'
    with pytest.raises(TallyParseError):
        parse_vouchers(bomb, "v.xml", max_bytes=MAX)


def test_too_large_is_refused():
    with pytest.raises(TallyTooLargeError):
        parse_vouchers(b"<ENVELOPE>" + b" " * 100 + b"</ENVELOPE>", "v.xml", max_bytes=50)


def test_illegal_control_characters_do_not_break_the_file():
    xml = vouchers_xml([sale("a")]).replace(b"Acme Traders", b"Acme&#4; Traders", 1)
    parsed = parse_vouchers(xml, "v.xml", max_bytes=MAX)
    assert len(parsed.vouchers) == 1


def test_a_formula_looking_ledger_name_is_skipped():
    v = voucher(guid="f", vtype="Journal", number="1", date="20250401",
                lines=[line("=HYPERLINK(1)", 10.0), line("Cash", -10.0)])
    parsed = parse_vouchers(vouchers_xml([v]), "v.xml", max_bytes=MAX)
    assert parsed.vouchers == [] and "formula" in parsed.skipped[0].reason


def test_a_file_with_no_vouchers_is_an_error():
    with pytest.raises(TallyParseError):
        parse_vouchers(b"<ENVELOPE><X/></ENVELOPE>", "v.xml", max_bytes=MAX)


def test_only_xml_is_accepted():
    with pytest.raises(TallyParseError):
        parse_vouchers(vouchers_xml([sale()]), "v.csv", max_bytes=MAX)


def test_a_voucher_with_too_many_lines_is_skipped():
    many = voucher(
        guid="m", vtype="Journal", number="1", date="20250401",
        lines=[line("Rent", 1.0) for _ in range(250)] + [line("Cash", -1.0) for _ in range(251)],
    )
    parsed = parse_vouchers(vouchers_xml([many]), "v.xml", max_bytes=MAX)
    assert parsed.vouchers == [] and "more than" in parsed.skipped[0].reason


def test_deeply_nested_xml_is_refused_or_read_without_crashing():
    deep = b"<ENVELOPE>" + b"<A>" * 20000 + b"</A>" * 20000 + b"</ENVELOPE>"
    with pytest.raises(TallyParseError):
        parse_vouchers(deep, "v.xml", max_bytes=MAX)  # well-formed, but holds no vouchers


def test_an_amount_that_is_not_a_number_skips_only_that_voucher():
    good = sale("ok")
    bad = sale("bad", "2", "20250402", amount=1181.0)
    data = vouchers_xml([good, bad]).replace(b"<AMOUNT>-1181.00</AMOUNT>", b"<AMOUNT>12abc</AMOUNT>")
    parsed = parse_vouchers(data, "v.xml", max_bytes=MAX)
    assert [v.guid for v in parsed.vouchers] == ["ok"]
    assert any("amount" in s.reason for s in parsed.skipped)


def test_bill_allocations_on_a_line_are_kept():
    v = voucher(
        guid="r", vtype="Receipt", number="9", date="20250410", party="Acme Traders",
        lines=[
            line("Bank One", 1180.0),
            line("Acme Traders", -1180.0, party=True, bills=[("INV-1", "Agst Ref", 1000.0), ("INV-2", "Agst Ref", 180.0)]),
        ],
    )
    parsed = parse_vouchers(vouchers_xml([v]), "v.xml", max_bytes=MAX)
    party_line = parsed.vouchers[0].lines[1]
    assert party_line.bills == (("INV-1", "Agst Ref", 100000), ("INV-2", "Agst Ref", 18000))
    assert parsed.vouchers[0].lines[0].bills == ()


def test_an_item_invoice_gets_its_sales_head_from_the_stock_items():
    v = voucher(
        guid="i1", vtype="Sales", number="5", date="20250401", party="Acme Traders",
        lines=[line("Acme Traders", 1180.0, party=True), line("Output CGST", -90.0), line("Output SGST", -90.0)],
        items=[("Oil 1L", "GST SALES", -600.0), ("Oil 15L", "GST SALES", -400.0)],
    )
    parsed = parse_vouchers(vouchers_xml([v]), "v.xml", max_bytes=MAX)
    got = {ln.ledger: ln.signed_paise for ln in parsed.vouchers[0].lines}
    assert got == {"Acme Traders": 118000, "Output CGST": -9000, "Output SGST": -9000, "GST SALES": -100000}
    assert sum(got.values()) == 0


def test_the_stock_items_of_an_item_invoice_are_kept_with_quantity_unit_and_value():
    v = voucher(
        guid="s1", vtype="Purchase", number="7", date="20250401", party="Zed Supplies",
        lines=[line("Zed Supplies", -1180.0, party=True), line("Input CGST", 90.0), line("Input SGST", 90.0)],
        items=[("Oil 1L", "GST PURCHASE", 600.0, "1,200 BOX"), ("Oil 15L", "GST PURCHASE", 400.0, "65.500 Kgs = 1 Nos"), ("No qty", "GST PURCHASE", 0.0)],
    )
    parsed = parse_vouchers(vouchers_xml([v]), "v.xml", max_bytes=MAX)
    items = [(i.name, i.unit, i.quantity, i.value_paise) for i in parsed.vouchers[0].items]
    assert items == [("Oil 1L", "BOX", "1200", 60000), ("Oil 15L", "Kgs", "65.500", 40000)]
