"""Deciding what a parsed voucher becomes. Pure: no database."""

from __future__ import annotations

import datetime

from classify.models import LedgerGroup as G
from ledger.models import BillKind, EntryKind, VoucherType
from ledger.tally_parse import normal_name
from ledger.tally_plan import Facts, Planned, Skip, plan_voucher
from ledger.tally_vouchers import ParsedVoucher, VoucherLine

CHART = {
    "Acme Traders": G.DEBTOR, "Zed Supplies": G.CREDITOR, "Cash": G.CASH, "Bank One": G.BANK, "Bank Two": G.BANK, "Bank Orphan": G.BANK,
    "Sales": G.SALES, "Purchases": G.PURCHASE, "Output CGST": G.DUTIES_AND_TAXES, "Output SGST": G.DUTIES_AND_TAXES,
    "Input CGST": G.DUTIES_AND_TAXES, "Input SGST": G.DUTIES_AND_TAXES, "Round Off": G.INDIRECT_EXPENSE, "Rent": G.INDIRECT_EXPENSE,
}
FACTS = Facts(
    groups={normal_name(k): v for k, v in CHART.items()},
    bank_ledgers=frozenset({normal_name("Bank One"), normal_name("Bank Two"), normal_name("Bank Orphan")}),
    accounts={normal_name("Bank One"): ("acct-1", False), normal_name("Bank Two"): ("acct-2", False)},
)


def voucher(tally_type, lines, *, number="1", party="", reference=""):
    return ParsedVoucher(
        ordinal=1, guid="g", tally_type=tally_type, number=number, date=datetime.date(2025, 4, 1), party=party,
        narration="", reference=reference, party_gstin="", own_gstin="",
        lines=tuple(VoucherLine(n, p, ip) for n, p, ip in lines),
    )


def test_a_credit_sale_becomes_a_voucher_and_a_bill():
    v = voucher("Sales", [("Acme Traders", 118000, True), ("Sales", -100000, False), ("Output CGST", -9000, False), ("Output SGST", -9000, False)], party="Acme Traders")
    plan = plan_voucher(v, FACTS)
    assert isinstance(plan, Planned)
    assert (plan.voucher_type, plan.entry_kind) == (VoucherType.SALES, EntryKind.VOUCHER)
    b = plan.bill
    assert (b.kind, b.taxable_paise, b.cgst_paise, b.sgst_paise, b.total_paise, b.round_off_paise) == (BillKind.SALES, 100000, 9000, 9000, 118000, 0)


def test_round_off_is_signed_and_the_bill_still_ties():
    v = voucher("Purchase", [("Zed Supplies", -118000, True), ("Purchases", 99999, False), ("Input CGST", 9000, False), ("Input SGST", 9000, False), ("Round Off", 1, False)], party="Zed Supplies")
    b = plan_voucher(v, FACTS).bill
    assert (b.kind, b.taxable_paise, b.round_off_paise, b.total_paise) == (BillKind.PURCHASE, 99999, 1, 118000)


def test_a_cash_sale_is_a_plain_voucher_without_a_bill():
    v = voucher("Sales", [("Cash", 1000, True), ("Sales", -1000, False)], party="Cash")
    plan = plan_voucher(v, FACTS)
    assert isinstance(plan, Planned) and plan.bill is None and plan.entry_kind == EntryKind.VOUCHER


def test_a_bill_that_does_not_tie_posts_without_a_bill_and_says_why():
    # Balanced, but tax sits on the party's own side, so no taxable value, tax and round-off can be derived from it.
    v = voucher("Sales", [("Acme Traders", 100000, True), ("Sales", -110000, False), ("Output CGST", 10000, False)], party="Acme Traders")
    plan = plan_voucher(v, FACTS)
    assert isinstance(plan, Planned) and plan.bill is None and plan.note


def test_an_unbalanced_voucher_is_skipped():
    v = voucher("Journal", [("Rent", 1000, False), ("Cash", -900, False)])
    assert isinstance(plan_voucher(v, FACTS), Skip)


def test_a_missing_ledger_is_skipped_and_named():
    v = voucher("Journal", [("Rent", 1000, False), ("Mystery", -1000, False)])
    out = plan_voucher(v, FACTS)
    assert isinstance(out, Skip) and "Mystery" in out.reason


def test_a_payment_from_a_bank_account_is_a_bank_entry():
    v = voucher("Payment", [("Rent", 1000, False), ("Bank One", -1000, False)])
    plan = plan_voucher(v, FACTS)
    assert (plan.voucher_type, plan.entry_kind, plan.bill) == (VoucherType.PAYMENT, EntryKind.BANK, None)
    assert plan.bank.counter == "Rent" and [(g.ledger, g.account_id, g.signed_paise) for g in plan.bank.legs] == [("Bank One", "acct-1", -1000)]


def test_a_contra_between_two_accounts_has_two_legs_and_no_counter():
    v = voucher("Contra", [("Bank Two", 5000, False), ("Bank One", -5000, False)])
    plan = plan_voucher(v, FACTS)
    assert plan.entry_kind == EntryKind.BANK and plan.bank.counter is None
    assert [g.account_id for g in plan.bank.legs] == ["acct-2", "acct-1"]


def test_a_bank_ledger_with_no_account_is_skipped_and_named():
    v = voucher("Payment", [("Rent", 1000, False), ("Bank Orphan", -1000, False)])
    out = plan_voucher(v, FACTS)
    assert isinstance(out, Skip) and "Bank Orphan" in out.reason and "bank account" in out.reason


def test_a_loan_account_waits_for_a_later_release():
    facts = Facts(FACTS.groups, FACTS.bank_ledgers, {normal_name("Bank One"): ("acct-1", True)})
    out = plan_voucher(voucher("Payment", [("Rent", 1000, False), ("Bank One", -1000, False)]), facts)
    assert isinstance(out, Skip) and "later release" in out.reason


def test_a_bank_voucher_with_three_lines_waits_for_a_later_release():
    v = voucher("Payment", [("Rent", 900, False), ("Round Off", 100, False), ("Bank One", -1000, False)])
    out = plan_voucher(v, FACTS)
    assert isinstance(out, Skip) and "later release" in out.reason


def test_a_cash_payment_is_a_journal_entry():
    v = voucher("Payment", [("Rent", 1000, False), ("Cash", -1000, False)])
    plan = plan_voucher(v, FACTS)
    assert (plan.entry_kind, plan.voucher_type, plan.bill) == (EntryKind.JOURNAL, VoucherType.PAYMENT, None)


def test_an_unknown_voucher_type_is_skipped():
    v = voucher("Delivery Note", [("Rent", 1, False), ("Cash", -1, False)])
    assert isinstance(plan_voucher(v, FACTS), Skip)


def test_a_purchase_whose_party_is_debited_is_skipped():
    v = voucher("Purchase", [("Zed Supplies", 1000, True), ("Purchases", -1000, False)], party="Zed Supplies")
    assert isinstance(plan_voucher(v, FACTS), Skip)


def test_a_nil_or_single_line_voucher_is_skipped():
    assert isinstance(plan_voucher(voucher("Journal", [("Rent", 0, False), ("Cash", 0, False)]), FACTS), Skip)
    assert isinstance(plan_voucher(voucher("Journal", [("Rent", 0, False)]), FACTS), Skip)


def test_a_credit_note_and_a_debit_note_are_bills_of_their_own_kind():
    cn = voucher("Credit Note", [("Acme Traders", -1000, True), ("Sales", 1000, False)], number="C1", party="Acme Traders")
    dn = voucher("Debit Note", [("Zed Supplies", 500, True), ("Purchases", -500, False)], number="D1", party="Zed Supplies")
    assert plan_voucher(cn, FACTS).bill.kind == BillKind.CREDIT_NOTE
    assert plan_voucher(dn, FACTS).bill.kind == BillKind.DEBIT_NOTE
