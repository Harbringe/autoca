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
    assert [(l.ledger, l.signed_paise, l.is_party) for l in v.lines] == [
        ("Acme Traders", 118000, True), ("Sales", -100000, False), ("Output CGST", -9000, False), ("Output SGST", -9000, False),
    ]
    assert parsed.company == "TEST CO" and parsed.date_from == parsed.date_to == datetime.date(2025, 4, 1)


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
