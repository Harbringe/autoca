"""Tally's grouped List of Ledgers (xlsx), and placing a party by what its Tally group is. No database."""

import datetime
import io

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

from classify.models import LedgerGroup as G
from ledger.tally_discover import _account_for, discover, master_groups
from ledger.tally_parse import TallyParseError, parse_masters
from ledger.tally_vouchers import ParsedVoucher, VoucherLine


def _report(rows) -> bytes:
    """A workbook shaped like Tally's List of Ledgers: a title block, then one column in which groups are bold and ledgers plain."""
    book = Workbook()
    sheet = book.active
    for text, bold in [("Acme Cloth", True), ("Town", False), ("List of Ledgers", True), ("1-Apr-25 to 31-Mar-26", False), *rows]:
        sheet.append([text])
        sheet.cell(row=sheet.max_row, column=1).font = Font(bold=bold)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_list_of_ledgers_report_is_read_by_its_bold_groups():
    data = _report(
        [
            ("Bank Accounts", True),
            ("Test Bank A/c 12345678", False),
            ("Cash-in-Hand", True),
            ("Cash", False),
            ("Wholesale Party", True),
            ("Sample Traders", False),
            ("Rent_x000D_\n", False),  # Excel's escaped carriage return is dropped from a name
            ("3 Group(s)", True),
            ("and", False),
        ]
    )
    parsed = parse_masters(data, "List Of Ledgers.xlsx", max_bytes=10**7)
    assert [(ln.name, ln.parent) for ln in parsed.ledgers] == [
        ("Test Bank A/c 12345678", "Bank Accounts"),
        ("Cash", "Cash-in-Hand"),
        ("Sample Traders", "Wholesale Party"),
        ("Rent", "Wholesale Party"),
    ]
    assert master_groups(parsed)["cash"][2] == G.CASH


def test_a_workbook_with_no_ledger_column_and_no_report_title_is_still_refused():
    book = Workbook()
    book.active.append(["nothing", "useful"])
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(TallyParseError):
        parse_masters(out.getvalue(), "x.xlsx", max_bytes=10**7)


def _purchase(party: str, number: str) -> ParsedVoucher:
    return ParsedVoucher(
        ordinal=1, guid=f"g{number}", tally_type="Purchase", number=number, date=datetime.date(2025, 5, 1), party=party,
        narration="", reference=number, party_gstin="", own_gstin="",
        lines=(VoucherLine(party, -1000, True), VoucherLine("Purchase 5%", 1000, False)),
    )


def test_a_ledger_in_the_firms_own_group_follows_what_most_of_that_group_turned_out_to_be():
    # "Wholesale Party" is not a standard group. Two of its ledgers are suppliers on purchases, so the third (only paid by bank) is one too.
    data = _report(
        [("Wholesale Party", True), ("Alpha Mills", False), ("Beta Mills", False), ("Gamma Mills", False)]
    )
    found = discover([_purchase("Alpha Mills", "1"), _purchase("Beta Mills", "2")], [], set(), master_groups(parse_masters(data, "l.xlsx", max_bytes=10**7)))
    by_name = {p.name: p for p in found.ledgers}
    assert {by_name[n].group for n in ("Alpha Mills", "Beta Mills", "Gamma Mills")} == {G.CREDITOR}
    assert by_name["Purchase 5%"].group == G.PURCHASE  # the head the purchases are booked to stays a head, not a party
    assert "2 of 2" in by_name["Gamma Mills"].reason and not by_name["Gamma Mills"].unsure


@pytest.mark.parametrize(
    "name, group, opens_an_account",
    [
        ("Test Bank CC 691", G.BANK_OD, True),
        ("Test Bank A/c 12345678", G.BANK, True),
        ("Person One Surname", G.LOAN, False),  # a person's unsecured loan is not an account at a bank
        ("Test Bank Gold Loan a/c 12345678", G.LOAN, True),
    ],
)
def test_which_ledgers_become_bank_accounts(name, group, opens_an_account):
    assert (_account_for(name, group) is not None) is opens_an_account
