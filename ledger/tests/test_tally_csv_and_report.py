"""Tally's grouped List of Ledgers (xlsx), the Day Book CSV, and placing a party by what its Tally group is. No database."""

import datetime
import io

import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

from classify.models import LedgerGroup as G
from ledger.tally_discover import _account_for, discover, master_groups
from ledger.tally_parse import TallyParseError, parse_masters
from ledger.tally_vouchers import ParsedVoucher, VoucherLine, parse_vouchers


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


CSV_HEAD = "Date,Voucher Type,Voucher No.,Ledger,Debit,Credit,Narration\n"


def test_day_book_csv_groups_rows_into_balanced_vouchers():
    text = (
        CSV_HEAD
        + "03-04-2025,Receipt,1,Test Bank,\"1,00,000.50\",,Cash sale\n"
        + ",,,Sample Customer,,\"1,00,000.50\",\n"
        + "04/04/2025,Payment,2,Rent,500,,\n"
        + ",,,Cash,,500,\n"
    )
    parsed = parse_vouchers(text.encode(), "daybook.csv", max_bytes=10**6)
    assert parsed.skipped == []
    assert [(v.tally_type, v.number, v.date) for v in parsed.vouchers] == [
        ("Receipt", "1", datetime.date(2025, 4, 3)),
        ("Payment", "2", datetime.date(2025, 4, 4)),
    ]
    assert [ln.signed_paise for ln in parsed.vouchers[0].lines] == [10000050, -10000050]
    assert parsed.vouchers[0].narration == "Cash sale"
    assert parsed.date_from == datetime.date(2025, 4, 3) and parsed.date_to == datetime.date(2025, 4, 4)


def test_csv_voucher_that_does_not_balance_is_left_out_with_the_reason():
    text = CSV_HEAD + "03-04-2025,Payment,1,Rent,100,,\n,,,Cash,,90,\n"
    parsed = parse_vouchers(text.encode(), "daybook.csv", max_bytes=10**6)
    assert parsed.vouchers == []
    assert "not equal" in parsed.skipped[0].reason


@pytest.mark.parametrize(
    "row, reason",
    [
        ("32-13-2025,Payment,1,Rent,100,,\n,,,Cash,,100,\n", "date"),
        ("03-04-2025,Payment,1,Rent,100.123,,\n,,,Cash,,100.123,\n", "decimals"),
        ("03-04-2025,Payment,1,=cmd(),100,,\n,,,Cash,,100,\n", "formula"),
    ],
)
def test_csv_bad_rows_skip_the_voucher_not_the_file(row, reason):
    parsed = parse_vouchers((CSV_HEAD + row).encode(), "daybook.csv", max_bytes=10**6)
    assert parsed.vouchers == []
    assert reason in parsed.skipped[0].reason.lower()


def test_csv_without_voucher_columns_is_refused_with_what_to_export():
    with pytest.raises(TallyParseError, match="Voucher Type"):
        parse_vouchers(b"Name,Group\nCash,Cash-in-Hand\n", "x.csv", max_bytes=10**6)


def test_reading_the_same_csv_twice_gives_the_same_voucher_ids():
    text = CSV_HEAD + "03-04-2025,Payment,1,Rent,100,,\n,,,Cash,,100,\n"
    one = parse_vouchers(text.encode(), "a.csv", max_bytes=10**6).vouchers[0].guid
    two = parse_vouchers(text.encode(), "b.csv", max_bytes=10**6).vouchers[0].guid
    assert one == two and one.startswith("csv:")


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
