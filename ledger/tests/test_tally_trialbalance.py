"""Reading Tally's trial balance and comparing it with the posted books."""

from __future__ import annotations

import datetime
import json
import xml.etree.ElementTree as ET

import pytest

from ledger.tally_parse import TallyParseError
from ledger.tally_trialbalance import Difference, compare, read_trial_balance
from ledger.tests.support import make_ledger, post
from ledger.tests.test_tally_voucher_import import (  # noqa: F401  (fixtures and helpers)
    G,
    client,
    firm,
    member,
    senior,
)

LIMIT = 10 * 1024 * 1024
ROWS = [("Cash", "1,000.00", ""), ("Capital", "", "-1,000.00"), ("Rent", "250.50", "")]


def _xml(rows) -> bytes:
    envelope = ET.Element("ENVELOPE")
    for name, debit, credit in rows:
        ET.SubElement(ET.SubElement(envelope, "DSPACCNAME"), "DSPDISPNAME").text = name
        info = ET.SubElement(envelope, "DSPACCINFO")
        ET.SubElement(ET.SubElement(info, "DSPCLDRAMT"), "DSPCLDRAMTA").text = debit
        ET.SubElement(ET.SubElement(info, "DSPCLCRAMT"), "DSPCLCRAMTA").text = credit
    return ET.tostring(envelope)


def _json(rows) -> bytes:
    names = [{"dspdispname": name} for name, _d, _c in rows]
    infos = [{"dspcldramt": {"dspcldramta": d}, "dspclcramt": {"dspclcramta": c}} for _n, d, c in rows]
    return json.dumps({"envelope": {"dspaccname": names, "dspaccinfo": infos}}).encode()


@pytest.mark.parametrize("make,name", [(_xml, "tb.xml"), (_json, "tb.json")])
def test_the_closing_balance_of_each_ledger_is_read_from_xml_and_from_json(make, name):
    assert read_trial_balance(make(ROWS), name, max_bytes=LIMIT) == {"Cash": 100000, "Capital": -100000, "Rent": 25050}


def test_a_file_that_is_not_a_trial_balance_is_refused():
    with pytest.raises(TallyParseError):
        read_trial_balance(b'{"hello": 1}', "tb.json", max_bytes=LIMIT)
    with pytest.raises(TallyParseError):
        read_trial_balance(_xml(ROWS), "tb.csv", max_bytes=LIMIT)


@pytest.mark.django_db
def test_compare_lists_the_ledgers_whose_closing_balance_differs(firm, client, senior):  # noqa: F811
    from core.db.session import firm_context

    with firm_context(firm.pk):
        cash, capital = make_ledger(client, "Cash", G.CASH), make_ledger(client, "Capital", G.CAPITAL)
        post(client, datetime.date(2025, 4, 5), cash, capital, 100000)  # Rs 1,000.00 in
        differences, matched = compare(client, 2025, {"Cash": 100000, "Capital": -90000, "Ghost": 500})
    assert matched == 1
    by_name = {d.name: d for d in differences}
    assert by_name["Capital"] == Difference("Capital", tally_paise=-90000, ours_paise=-100000)
    assert by_name["Ghost"].ours_paise == 0 and by_name["Ghost"].tally_paise == 500
    assert "Cash" not in by_name


@pytest.mark.django_db
def test_names_are_compared_the_way_the_importer_compares_them(firm, client, senior):  # noqa: F811
    from core.db.session import firm_context

    with firm_context(firm.pk):
        post(client, datetime.date(2025, 4, 5), make_ledger(client, "Cash", G.CASH), make_ledger(client, "Capital", G.CAPITAL), 100000)
        differences, matched = compare(client, 2025, {"  CASH ": 100000, "capital": -100000})
    assert differences == [] and matched == 2
