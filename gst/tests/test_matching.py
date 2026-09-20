"""The reconciliation rules, one behaviour per test, over plain dataclasses."""

import datetime

from core.identifiers import gstin_check_character
from gst.matching import (
    Invoice,
    ItcStatus,
    MatchKind,
    Section,
    blocked_reason,
    normalise_invoice_no,
    reconcile,
)

PERIOD = datetime.date(2026, 8, 1)
D = datetime.date(2026, 8, 10)


def gstin(seed: str) -> str:
    body = f"27{seed}1Z"
    body = body[:14]
    return body + gstin_check_character(body)


VENDOR = gstin("AAAPL1234C")
OTHER = gstin("BBBPL5678D")


def inv(no, *, g=VENDOR, igst=0, cgst=900_00, sgst=900_00, taxable=10_000_00, **kw):
    return Invoice(
        ref=kw.pop("ref", no),
        gstin=g,
        invoice_no=no,
        invoice_date=kw.pop("date", D),
        taxable_paise=taxable,
        igst_paise=igst,
        cgst_paise=cgst,
        sgst_paise=sgst,
        **kw,
    )


def kinds(result):
    return sorted(m.kind.value for m in result.matches)


def test_gstin_helper_builds_valid_gstins():
    from core.identifiers import is_valid_gstin

    assert is_valid_gstin(VENDOR) and is_valid_gstin(OTHER)


def test_invoice_number_forms_that_are_one_invoice():
    assert normalise_invoice_no("INV/0042") == normalise_invoice_no("inv-42")
    assert normalise_invoice_no("INV 042") == normalise_invoice_no("INV42")
    assert normalise_invoice_no("0042") == "42"
    assert normalise_invoice_no("A1") != normalise_invoice_no("A10")


def test_exact_match_is_eligible():
    r = reconcile([inv("INV-1")], [inv("INV-1")], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.MATCHED and m.itc_status is ItcStatus.ELIGIBLE
    assert m.eligible_paise == 1800_00
    assert r.summary.eligible_paise == 1800_00
    assert r.actions() == []


def test_rounding_within_a_rupee_still_matches():
    r = reconcile([inv("1", cgst=900_00)], [inv("1", cgst=900_99)], period_start=PERIOD)
    assert r.matches[0].kind is MatchKind.MATCHED
    # credit is the smaller of the two per head
    assert r.matches[0].eligible_paise == 900_00 + 900_00


def test_more_than_a_rupee_is_an_amount_mismatch_with_no_credit():
    r = reconcile([inv("1", cgst=900_00)], [inv("1", cgst=902_00)], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.AMOUNT_MISMATCH
    assert m.differences == {"cgst_paise": -2_00}
    assert m.eligible_paise == 0 and m.ineligible_paise == 1800_00


def test_in_books_not_in_portal_recent_is_timing():
    r = reconcile([inv("9", date=datetime.date(2026, 8, 28))], [], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.MISSING_IN_2B and m.timing
    assert "follow up" in m.action.lower()


def test_in_books_not_in_portal_old_is_not_timing():
    r = reconcile([inv("9", date=datetime.date(2026, 5, 2))], [], period_start=PERIOD)
    assert r.matches[0].kind is MatchKind.MISSING_IN_2B and not r.matches[0].timing


def test_in_portal_not_in_books():
    r = reconcile([], [inv("77")], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.MISSING_IN_BOOKS
    assert r.summary.unclaimed_in_2b_paise == 1800_00
    assert r.summary.eligible_paise == 0


def test_mistyped_invoice_number_is_only_a_suggestion():
    r = reconcile([inv("INV-1234")], [inv("INV-1243")], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.POSSIBLE_MATCH
    assert m.book.invoice_no == "INV-1234" and m.portal.invoice_no == "INV-1243"
    assert m.eligible_paise == 0  # never credited until a person confirms


def test_different_supplier_is_never_a_possible_match():
    r = reconcile([inv("5", g=VENDOR)], [inv("5", g=OTHER)], period_start=PERIOD)
    assert kinds(r) == ["missing_in_2b", "missing_in_books"]


def test_duplicate_in_register_counted_once_for_credit():
    r = reconcile([inv("1"), inv("1", ref="again")], [inv("1")], period_start=PERIOD)
    assert kinds(r) == ["duplicate", "matched"]
    assert r.summary.eligible_paise == 1800_00


def test_invalid_gstin():
    bad = "27AAAPL1234C1ZX"
    r = reconcile([inv("1", g=bad), inv("2", g="")], [], period_start=PERIOD)
    assert kinds(r) == ["invalid_gstin", "invalid_gstin"]


def test_reverse_charge_is_liability_not_2b_credit():
    r = reconcile([inv("1", rcm=True)], [], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.RCM and m.itc_status is ItcStatus.RCM_ON_PAYMENT
    assert r.summary.rcm_liability_paise == 1800_00
    assert r.summary.eligible_paise == 0


def test_blocked_by_hsn_and_by_category_and_by_override():
    assert blocked_reason(inv("1", hsn="87032291"))
    assert blocked_reason(inv("1", category="Staff food & beverages"))
    assert blocked_reason(inv("1", blocked=True))
    assert not blocked_reason(inv("1", hsn="4820", category="Stationery"))
    r = reconcile([inv("1", hsn="8703")], [inv("1")], period_start=PERIOD)
    (m,) = r.matches
    assert m.kind is MatchKind.MATCHED and m.itc_status is ItcStatus.BLOCKED
    assert r.summary.blocked_paise == 1800_00 and r.summary.eligible_paise == 0


def test_credit_note_reduces_credit():
    r = reconcile(
        [inv("1"), inv("CN1", section=Section.CDN, cgst=100_00, sgst=100_00)],
        [inv("1"), inv("CN1", section=Section.CDN, cgst=100_00, sgst=100_00)],
        period_start=PERIOD,
    )
    assert r.summary.eligible_paise == 1800_00 - 200_00


def test_same_result_every_time():
    books = [inv("1"), inv("2", cgst=1), inv("3")]
    portal = [inv("1"), inv("2"), inv("9")]
    a = reconcile(books, portal, period_start=PERIOD)
    b = reconcile(books, portal, period_start=PERIOD)
    assert a == b
