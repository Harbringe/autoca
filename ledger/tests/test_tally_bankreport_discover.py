"""Reading a Tally bank report, and working out which ledgers and accounts a set of files implies. Pure: no database."""

from __future__ import annotations

import datetime

import pytest

from classify.models import LedgerGroup as G
from ledger.tally_bankreport import looks_like_bank_report, parse_bank_report
from ledger.tally_discover import discover, name_group
from ledger.tally_parse import TallyParseError
from ledger.tally_vouchers import parse_vouchers
from ledger.tests.tally_voucher_xml import bank_report_xml, line, report_row, voucher, vouchers_xml

MAX = 10 * 1024 * 1024


def report(*rows):
    return parse_bank_report(bank_report_xml(rows), "bank.xml", max_bytes=MAX)


def test_a_receipt_is_money_in_and_a_payment_is_money_out():
    parsed = report(
        report_row("4-Apr-25", "Cash", "Rcpt", debit=1501.0, number="1"),
        report_row("4-Apr-25", "Bank Charges", "Pymt", credit=1.2, number="2", narration="SMS charges"),
    )
    got = [(r.date, r.counter, r.voucher_type, r.number, r.signed_paise, r.narration) for r in parsed.rows]
    assert got == [
        (datetime.date(2025, 4, 4), "Cash", "Receipt", "1", 150100, ""),
        (datetime.date(2025, 4, 4), "Bank Charges", "Payment", "2", -120, "SMS charges"),
    ]
    assert parsed.date_from == parsed.date_to == datetime.date(2025, 4, 4)


def test_a_row_with_several_other_ledgers_is_left_out_with_the_reason():
    parsed = report(report_row("5-Apr-25", "(as per details)", "Pymt", credit=500.0, number="3"), report_row("5-Apr-25", "Rent Paid", "Pymt", credit=10.0, number="4"))
    assert [r.counter for r in parsed.rows] == ["Rent Paid"]
    assert "several ledgers" in parsed.skipped[0].reason and parsed.skipped[0].name == "3"


def test_a_report_is_told_from_a_voucher_export():
    assert looks_like_bank_report(bank_report_xml([report_row("4-Apr-25", "Cash", "Rcpt", debit=1.0)]))
    assert not looks_like_bank_report(vouchers_xml([]))


def test_a_report_with_a_doctype_or_no_rows_is_refused():
    with pytest.raises(TallyParseError):
        parse_bank_report(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>', "b.xml", max_bytes=MAX)
    with pytest.raises(TallyParseError):
        parse_bank_report(b"<ENVELOPE><X/></ENVELOPE>", "b.xml", max_bytes=MAX)


@pytest.mark.parametrize(
    "name, group",
    [
        ("Cash", G.CASH),
        ("SBI SB A/C 62139251173", G.BANK),
        ("SBI CC A/C 37563283596", G.LOAN),
        ("Output CGST 9%", G.DUTIES_AND_TAXES),
        ("TCS Receivable", G.CURRENT_ASSET),
        ("R/F", G.INDIRECT_EXPENSE),
        ("Suspense", G.SUSPENSE),
    ],
)
def test_a_name_that_settles_the_group(name, group):
    assert name_group(name)[0] == group


def test_a_name_that_says_nothing_settles_nothing():
    assert name_group("Rent Paid") is None


def test_the_groups_come_from_the_part_each_ledger_plays_in_a_voucher():
    sale = voucher(
        guid="s", vtype="Sales", number="1", date="20250401", party="Acme Traders",
        lines=[line("Acme Traders", 1180.0, party=True), line("GST SALE", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)],
    )
    buy = voucher(
        guid="p", vtype="Purchase", number="2", date="20250402", party="Zed Supplies",
        lines=[line("Zed Supplies", -1180.0, party=True), line("GST PURCHASE", 1000.0), line("Input CGST", 90.0), line("Input SGST", 90.0)],
    )
    vouchers = parse_vouchers(vouchers_xml([sale, buy]), "v.xml", max_bytes=MAX).vouchers
    found = {p.name: p for p in discover(vouchers, [], set()).ledgers}
    assert found["Acme Traders"].group == G.DEBTOR and found["Zed Supplies"].group == G.CREDITOR
    assert found["GST SALE"].group == G.SALES and found["GST PURCHASE"].group == G.PURCHASE
    assert found["Input CGST"].group == G.DUTIES_AND_TAXES
    assert not found["Acme Traders"].unsure


def test_ledgers_the_client_already_has_are_left_alone():
    sale = voucher(
        guid="s", vtype="Sales", number="1", date="20250401", party="Acme Traders",
        lines=[line("Acme Traders", 100.0, party=True), line("GST SALE", -100.0)],
    )
    vouchers = parse_vouchers(vouchers_xml([sale]), "v.xml", max_bytes=MAX).vouchers
    names = [p.name for p in discover(vouchers, [], {"gst sale"}).ledgers]
    assert names == ["Acme Traders"]


def test_a_bank_report_proposes_its_own_account_and_guesses_the_others_as_unsure():
    rep = report(
        report_row("4-Apr-25", "Kirti Oil Industries Pvt Ltd", "Pymt", credit=5000.0, number="1"),
        report_row("5-Apr-25", "Rent Paid", "Pymt", credit=100.0, number="2"),
        report_row("6-Apr-25", "Cash", "Rcpt", debit=300.0, number="3"),
    )
    d = discover([], [("SBI SB A/C 62139251173", rep)], set())
    by = {p.name: p for p in d.ledgers}
    assert by["SBI SB A/C 62139251173"].group == G.BANK
    assert (by["Kirti Oil Industries Pvt Ltd"].group, by["Kirti Oil Industries Pvt Ltd"].unsure) == (G.CREDITOR, True)
    assert (by["Rent Paid"].group, by["Rent Paid"].unsure) == (G.INDIRECT_EXPENSE, True)
    assert by["Cash"].group == G.CASH
    assert [(a.ledger, a.kind, a.bank_code, a.account_number) for a in d.accounts] == [("SBI SB A/C 62139251173", "BANK", "SBI", "62139251173")]
