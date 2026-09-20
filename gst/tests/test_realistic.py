"""The behaviours that make this match how a CA actually reads GSTR-2B and Tally."""

from __future__ import annotations

import datetime
import json

import pytest

from core.db.session import firm_context
from core.identifiers import gstin_check_character
from core.provisioning import create_client, create_firm
from gst import report, services
from gst.matching import Invoice, ItcStatus, MatchKind, Section, reconcile
from gst.parsers import parse_gstr2b_json, parse_register
from gst.tests.test_matching import PERIOD, VENDOR, D, inv


def kinds(r):
    return sorted(m.kind.value for m in r.matches)


# ---- the engine ----------------------------------------------------------------


def test_portal_saying_itc_not_available_is_respected():
    portal = Invoice(**{**inv("1").__dict__, "itc_available": False, "itc_reason": "P"})
    (m,) = reconcile([inv("1")], [portal], period_start=PERIOD).matches
    assert m.kind is MatchKind.MATCHED and m.itc_status is ItcStatus.NOT_ELIGIBLE
    assert m.eligible_paise == 0 and m.ineligible_paise == 1800_00
    assert "not available" in m.cause and "P" in m.cause


def test_same_total_tax_on_different_heads_is_a_tax_head_mismatch():
    book = inv("1", igst=1800_00, cgst=0, sgst=0)
    portal = inv("1", igst=0, cgst=900_00, sgst=900_00)
    (m,) = reconcile([book], [portal], period_start=PERIOD).matches
    assert m.kind is MatchKind.TAX_HEAD_MISMATCH and "place-of-supply" in m.cause


def test_invoice_in_another_months_2b_is_wrong_period_not_missing():
    other = {(VENDOR, "9"): datetime.date(2026, 9, 1)}
    (m,) = reconcile([inv("9")], [], period_start=PERIOD, other_periods=other).matches
    assert m.kind is MatchKind.WRONG_PERIOD and "September 2026" in m.action


def test_credit_already_taken_in_an_earlier_month_is_not_taken_again():
    taken = {(VENDOR, "1"): datetime.date(2026, 7, 1)}
    r = reconcile([inv("1")], [inv("1")], period_start=PERIOD, claimed_elsewhere=taken)
    (m,) = r.matches
    assert m.kind is MatchKind.DUPLICATE and "July 2026" in m.cause
    assert r.summary.eligible_paise == 0


def test_an_amended_invoice_matches_the_original_number_in_the_register():
    amended = Invoice(**{**inv("INV-1A").__dict__, "original_no": "INV-1"})
    r = reconcile([inv("INV-1")], [amended], period_start=PERIOD)
    assert kinds(r) == ["matched"]


def test_portal_marking_reverse_charge_is_treated_as_rcm():
    portal = Invoice(**{**inv("1").__dict__, "rcm": True})
    (m,) = reconcile([inv("1")], [portal], period_start=PERIOD).matches
    assert m.kind is MatchKind.RCM and m.itc_status is ItcStatus.RCM_ON_PAYMENT


def test_imports_and_isd_are_portal_only_credit_to_verify():
    imp = Invoice(ref="2b:1", gstin="", invoice_no="BOE1", invoice_date=D, igst_paise=500_00,
                  section=Section.IMPG)
    isd = Invoice(ref="2b:2", gstin=VENDOR, invoice_no="ISD9", invoice_date=D, cgst_paise=50_00,
                  section=Section.ISD)
    r = reconcile([], [imp, isd], period_start=PERIOD)
    assert kinds(r) == ["import", "isd_credit"]
    assert r.summary.eligible_paise == 550_00


# ---- the parsers on real-shaped input ------------------------------------------


def portal_doc():
    return json.dumps({"data": {"gstin": "29ABCPE1234F1Z5", "rtnprd": "082026", "docdata": {
        "b2b": [{"ctin": VENDOR, "trdnm": "Acme", "supfildt": "11-09-2026", "inv": [
            {"inum": "A/1", "typ": "R", "dt": "05-08-2026", "val": 11800.0, "pos": "27",
             "rev": "N", "itcavl": "N", "rsn": "P", "txval": 10000.0, "igst": 0,
             "cgst": 900.0, "sgst": 900.0, "cess": 0}]}],
        "b2ba": [{"ctin": VENDOR, "inv": [{"inum": "A/2A", "oinum": "A/2", "dt": "06-08-2026",
                                            "txval": 100, "cgst": 9, "sgst": 9, "itcavl": "Y"}]}],
        "cdnr": [{"ctin": VENDOR, "nt": [
            {"ntnum": "C1", "typ": "C", "dt": "07-08-2026", "txval": 100, "cgst": 9, "sgst": 9},
            {"ntnum": "D1", "typ": "D", "dt": "08-08-2026", "txval": 100, "cgst": 9, "sgst": 9}]}],
        "impg": [{"boenum": "555", "boedt": "09-08-2026", "portcode": "INMUN1",
                  "txval": 1000.0, "igst": 180.0}],
        "isd": [{"ctin": VENDOR, "doclist": [{"docnum": "I1", "docdt": "10-08-2026", "cgst": 5.0}]}],
    }}}).encode()


def test_all_the_2b_sections_and_the_itc_flag_are_read():
    p = parse_gstr2b_json(portal_doc())
    by = {i.invoice_no: i for i in p.invoices}
    assert not by["A/1"].itc_available and by["A/1"].itc_reason == "P"
    assert by["A/2A"].original_no == "A/2"
    assert by["C1"].section is Section.CDN and by["D1"].section is Section.DN
    assert by["555"].section is Section.IMPG and by["555"].igst_paise == 18000
    assert by["I1"].section is Section.ISD and by["I1"].cgst_paise == 500


def test_a_debit_note_from_the_supplier_adds_credit_a_credit_note_removes_it():
    assert Invoice(ref="x", gstin="", invoice_no="1", invoice_date=None, section=Section.CDN).sign == -1
    assert Invoice(ref="x", gstin="", invoice_no="1", invoice_date=None, section=Section.DN).sign == 1


TALLY = (
    "Sharma Traders,,,,,,,,,\n"
    "Purchase Register,,,,,,,,,\n"
    "1-Aug-26 to 31-Aug-26,,,,,,,,,\n"
    "Date,Particulars,Voucher Type,Voucher No.,Supplier Invoice No.,Supplier Invoice Date,"
    "GSTIN/UIN,Value,Input CGST 9%,Input SGST 9%,Input CGST 2.5%,Input SGST 2.5%,Gross Total\n"
    f"05-Aug-26,Acme Traders,Purchase,P/12,INV-88,03-Aug-26,{VENDOR},\"10,000.00\","
    "900.00,900.00,0,0,\"11,800.00\"\n"
    f"09-Aug-26,Beta Supplies,Purchase,P/13,B-5,08-Aug-26,{VENDOR},2000,0,0,50,50,2100\n"
)


def test_a_tally_purchase_register_export_is_read_as_tally_writes_it():
    a, b = parse_register(TALLY.encode(), "Purchase Register.csv")
    # the supplier's own invoice number, not Tally's voucher number
    assert (a.invoice_no, b.invoice_no) == ("INV-88", "B-5")
    assert a.supplier_name == "Acme Traders" and a.invoice_date == datetime.date(2026, 8, 3)
    assert a.taxable_paise == 1_000_000 and a.cgst_paise == 90_000
    # one tax head split across rate columns is summed
    assert (b.cgst_paise, b.sgst_paise) == (5_000, 5_000)


# ---- across months, and the 3B table --------------------------------------------

pytestmark_db = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

ME = "27" + "AAAPL1234C1Z"
ME = ME + gstin_check_character(ME)


def _portal_json(period, invoices):
    return json.dumps({"data": {"gstin": ME, "rtnprd": period, "docdata": {
        "b2b": [{"ctin": VENDOR, "trdnm": "Acme", "inv": invoices}]}}}).encode()


def _register(rows):
    head = "GSTIN,Invoice No,Date,Taxable Value,CGST,SGST\n"
    return (head + "".join(f"{VENDOR},{n},{d},{t},{c},{c}\n" for n, d, t, c in rows)).encode()


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_across_months_and_the_3b_table():
    firm = create_firm("Months Firm")
    client = create_client(firm, "Arjun", datetime.date(2026, 4, 1))
    with firm_context(firm.pk):
        reg = services.add_registration(client, ME)
        aug = services.get_or_create_run(reg, datetime.date(2026, 8, 1), None)
        sep = services.get_or_create_run(reg, datetime.date(2026, 9, 1), None)

        # August: INV-1 is in 2B and taken. INV-2 is in the register but only turns up in September's 2B.
        services.load_register(aug, _register([("INV-1", "05-08-2026", 10000, 900),
                                               ("INV-2", "20-08-2026", 5000, 450)]), "a.csv", None)
        services.load_portal(aug, _portal_json("082026", [
            {"inum": "INV-1", "dt": "05-08-2026", "txval": 10000, "cgst": 900, "sgst": 900}]),
            "a.json", None)
        # September: INV-2 arrives; the register also repeats INV-1 by mistake.
        services.load_register(sep, _register([("INV-1", "05-08-2026", 10000, 900),
                                               ("INV-2", "20-08-2026", 5000, 450)]), "s.csv", None)
        services.load_portal(sep, _portal_json("092026", [
            {"inum": "INV-2", "dt": "20-08-2026", "txval": 5000, "cgst": 450, "sgst": 450}]),
            "s.json", None)

        services.reconcile_run(sep)  # September first: nothing else has been claimed yet
        services.reconcile_run(aug)  # now August sees September's 2B
        aug_kinds = {m.kind for m in aug.matches.all()}
        assert aug_kinds == {"matched", "wrong_period"}

        services.reconcile_run(sep)  # and September sees August already took INV-1
        sep_kinds = {m.kind for m in sep.matches.all()}
        assert sep_kinds == {"duplicate", "matched"}
        assert services.summarise(sep)["eligible_paise"] == 900_00

        table = {line["code"]: line for line in report.gstr3b_table4(aug)}
        assert table["4A(5)"]["cgst_paise"] == 900_00 and table["4A(5)"]["sgst_paise"] == 900_00
        assert table["4B(1)"]["cgst_paise"] == 0
