"""Reading Tally's voucher-type master, and what the planner does with types that leave nothing in the books. Pure: no database."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from ledger.tally_parse import TallyParseError, normal_name
from ledger.tally_vtypes import read_voucher_types, suggest_mapping

LIMIT = 10 * 1024 * 1024
TYPES = {"GST SALE": "Sales", "Retail": "GST SALE", "Quote": "Sales Order", "Odd": "Reversing Journal", "Sales": "Sales"}


def _xml(types) -> bytes:
    envelope = ET.Element("ENVELOPE")
    holder = ET.SubElement(ET.SubElement(ET.SubElement(envelope, "BODY"), "DATA"), "TALLYMESSAGE")
    for name, parent in types.items():
        node = ET.SubElement(holder, "VOUCHERTYPE", {"NAME": name})
        ET.SubElement(node, "PARENT").text = parent
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(envelope)


def _json(types) -> bytes:
    messages = [{"metadata": {"type": "Voucher Type", "name": name}, "parent": parent} for name, parent in types.items()]
    return json.dumps({"tallymessage": messages}).encode()


@pytest.mark.parametrize("make,name", [(_xml, "types.xml"), (_json, "types.json")])
def test_the_parent_of_each_voucher_type_is_read_from_xml_and_from_json(make, name):
    assert read_voucher_types(make(TYPES), name, max_bytes=LIMIT) == TYPES


def test_a_firms_own_types_count_as_the_standard_type_they_were_made_from():
    suggested = suggest_mapping(TYPES)
    assert suggested["GST SALE"] == "sales"
    assert suggested["Retail"] == "sales", "a type made from another of the firm's types follows the chain to a standard one"
    assert suggested["Quote"] == "none", "an order leaves nothing in the books"
    assert "Odd" not in suggested, "a reversing journal is not imported, so the person is still asked"
    assert "Sales" not in suggested, "Tally's own types are never remapped"


def test_a_chain_that_loops_ends_instead_of_hanging():
    assert suggest_mapping({"A": "B", "B": "A"}) == {}


def test_a_file_that_is_not_a_voucher_type_list_is_refused():
    with pytest.raises(TallyParseError):
        read_voucher_types(b'{"hello": 1}', "t.json", max_bytes=LIMIT)
    with pytest.raises(TallyParseError):
        read_voucher_types(_xml({}), "t.xml", max_bytes=LIMIT)
    with pytest.raises(TallyParseError):
        read_voucher_types(_xml(TYPES), "t.csv", max_bytes=LIMIT)


def test_a_file_with_a_doctype_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>'
    with pytest.raises(TallyParseError):
        read_voucher_types(bomb, "t.xml", max_bytes=LIMIT)


def test_names_are_matched_the_way_the_importer_matches_them():
    assert suggest_mapping({"  gst   sale ": "SALES"})["  gst   sale "] == "sales"
    assert normal_name("  gst   sale ") == "gst sale"
