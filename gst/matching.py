"""Purchase register against GSTR-2B: the matching and the ITC arithmetic.

Pure functions over plain dataclasses. No database, no request, no clock -- so
every rule below is testable with a list literal, and the same code can be run
again on the same inputs and give the same answer. Persisting the result, and
letting a CA overrule it, is ``gst.services``'s job, not this module's.

What this module will and will not decide
-----------------------------------------
It **classifies** each register row against the portal data and works out the
credit that *would* be eligible. It never treats a fuzzy match as a match: a
row that only looks like a typo of a portal invoice is reported as
``POSSIBLE_MATCH`` and earns no credit until a person confirms it. Nothing here
is final. ITC eligibility is a determination that feeds a filing, and the CA
who signs it off is the one answerable for it.

Money is integer paise throughout (``core.money``). The tolerance is one rupee
per tax head, applied as a subtraction of two integers.
"""

from __future__ import annotations

import datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from core.identifiers import is_valid_gstin
from core.identity import normalise_gstin, normalise_invoice_no
from core.money import PAISE

#: One rupee per tax head. GST amounts are conventionally rounded to the rupee,
#: so a difference no bigger than this is rounding, not a mismatch.
TOLERANCE_PAISE = PAISE

TAX_HEADS = ("igst_paise", "cgst_paise", "sgst_paise", "cess_paise")


class Section(str, Enum):
    B2B = "B2B"
    #: A credit note from the supplier, or a purchase return (Tally's "Debit
    #: Note"). Reduces the credit claimed.
    CDN = "CDN"
    #: A debit note from the supplier: it *adds* to the credit.
    DN = "DN"
    #: Import of goods, per the bill of entry. Reported on the portal only.
    IMPG = "IMPG"
    #: Credit distributed by an Input Service Distributor.
    ISD = "ISD"


class MatchKind(str, Enum):
    MATCHED = "matched"
    AMOUNT_MISMATCH = "amount_mismatch"
    #: Looks like the same invoice under a mistyped number. A suggestion only.
    POSSIBLE_MATCH = "possible_match"
    MISSING_IN_2B = "missing_in_2b"
    MISSING_IN_BOOKS = "missing_in_books"
    DUPLICATE = "duplicate"
    INVALID_GSTIN = "invalid_gstin"
    #: Reverse charge: the client pays the tax; there is no 2B credit to match.
    RCM = "rcm"
    #: Same total tax as the portal but split across heads differently -- the
    #: usual sign of a place-of-supply error (IGST booked as CGST+SGST, or back).
    TAX_HEAD_MISMATCH = "tax_head_mismatch"
    #: The invoice is in a different month's GSTR-2B than this one.
    WRONG_PERIOD = "wrong_period"
    #: Import of goods on the portal: verify against the bill of entry.
    IMPORT = "import"
    #: Credit distributed by an ISD, on the portal only.
    ISD_CREDIT = "isd_credit"


class ItcStatus(str, Enum):
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    #: Not claimable yet or not on this evidence -- needs a person or a later 2B.
    NOT_ELIGIBLE = "not_eligible"
    #: Reverse charge: claimable only after the tax is paid in cash.
    RCM_ON_PAYMENT = "rcm_on_payment"


@dataclass(frozen=True)
class Invoice:
    """One line of either dataset, in the same shape so they compare directly."""

    ref: str  # caller's handle for the row (a pk, or "row 12")
    gstin: str
    invoice_no: str
    invoice_date: datetime.date | None
    taxable_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    supplier_name: str = ""
    hsn: str = ""
    #: Free text the CA's staff wrote against the row: ledger head, nature of
    #: expense. Only used to spot blocked-credit categories.
    category: str = ""
    section: Section = Section.B2B
    rcm: bool = False
    #: GSTR-2B's own verdict: "itcavl" is N for credit the portal says cannot be
    #: taken (section 17(5), place of supply, and so on), with a reason code.
    itc_available: bool = True
    itc_reason: str = ""
    #: For an amended invoice on the portal, the number it replaces. The
    #: register may still carry that original number.
    original_no: str = ""
    #: Set by a person to say "this is blocked" regardless of what the rules think.
    blocked: bool = False

    @property
    def tax_paise(self) -> int:
        return sum(getattr(self, h) for h in TAX_HEADS)

    @property
    def sign(self) -> int:
        return -1 if self.section is Section.CDN else 1

    @property
    def key(self) -> tuple[str, str]:
        return (normalise_gstin(self.gstin), normalise_invoice_no(self.invoice_no))


@dataclass(frozen=True)
class Match:
    kind: MatchKind
    book: Invoice | None
    portal: Invoice | None
    itc_status: ItcStatus
    #: Credit that would be claimable on this row, in paise. Negative for a
    #: credit note. Zero unless ``itc_status`` is ELIGIBLE.
    eligible_paise: int
    #: Credit that is on the row but not claimable (blocked, or not in 2B).
    ineligible_paise: int
    cause: str
    action: str
    #: Per tax head, book minus portal, for an amount mismatch.
    differences: dict[str, int] = field(default_factory=dict)
    #: True when the likeliest explanation is that the supplier has not filed
    #: yet -- a difference in timing, not an error.
    timing: bool = False


@dataclass(frozen=True)
class Summary:
    counts: dict[str, int]
    eligible_paise: int
    blocked_paise: int
    ineligible_paise: int
    rcm_liability_paise: int
    #: Tax on portal invoices nobody has booked. Not claimable until booked.
    unclaimed_in_2b_paise: int


@dataclass(frozen=True)
class Reconciliation:
    matches: list[Match]
    summary: Summary

    def by_kind(self) -> dict[MatchKind, list[Match]]:
        grouped: dict[MatchKind, list[Match]] = defaultdict(list)
        for m in self.matches:
            grouped[m.kind].append(m)
        return grouped

    def actions(self) -> list[str]:
        """The work list: one line per row that needs somebody to do something."""
        return [m.action for m in self.matches if m.action]


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------

#: ``normalise_invoice_no`` and ``normalise_gstin`` are imported from ``core.identity``, imported at the top of this
#: file: the books use the same definition of "the same invoice", and ``gst/`` must not own it.

# ---------------------------------------------------------------------------
# Blocked credit (section 17(5)) -- defaults, and always overridable
# ---------------------------------------------------------------------------

#: HSN/SAC prefixes for categories the requirements document names: motor
#: vehicles, food and beverages, club memberships. This is a starting point a
#: CA can overrule per row (``Invoice.blocked``), not a statement of law: the
#: exceptions in section 17(5) are exactly the kind of thing a person decides.
BLOCKED_HSN_PREFIXES = (
    "8702",  # motor vehicles for ten or more persons
    "8703",  # motor cars
    "996331",  # restaurant services
    "996332",  # outdoor catering
    "999595",  # membership of a club
)

BLOCKED_KEYWORDS = (
    "motor car",
    "motor vehicle",
    "vehicle",
    "food",
    "beverage",
    "catering",
    "restaurant",
    "club",
    "membership",
)


def blocked_reason(inv: Invoice) -> str:
    """Why this invoice's credit is blocked by default, or '' if it is not."""
    if inv.blocked:
        return "marked as blocked credit"
    hsn = re.sub(r"\D", "", inv.hsn or "")
    for prefix in BLOCKED_HSN_PREFIXES:
        if hsn.startswith(prefix):
            return f"HSN/SAC {hsn} is a blocked-credit category"
    text = (inv.category or "").lower()
    for word in BLOCKED_KEYWORDS:
        if word in text:
            return f"'{word}' is a blocked-credit category"
    return ""


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------


def _differences(book: Invoice, portal: Invoice) -> dict[str, int]:
    """Heads where the two differ by more than the rounding tolerance."""
    diffs = {}
    for head in ("taxable_paise", *TAX_HEADS):
        delta = getattr(book, head) - getattr(portal, head)
        if abs(delta) > TOLERANCE_PAISE:
            diffs[head] = delta
    return diffs


def _edit_distance_at_most_two(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 2:
        return False
    if a == b:
        return True
    # Small strings; a straightforward DP is clearer than a clever bound.
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 2


def _looks_like_same_invoice(book: Invoice, portal: Invoice) -> bool:
    """Same supplier, same tax within tolerance, and a near-identical number or date."""
    if book.gstin != portal.gstin:
        return False
    if abs(book.tax_paise - portal.tax_paise) > TOLERANCE_PAISE * len(TAX_HEADS):
        return False
    same_date = book.invoice_date is not None and book.invoice_date == portal.invoice_date
    close_no = _edit_distance_at_most_two(
        normalise_invoice_no(book.invoice_no), normalise_invoice_no(portal.invoice_no)
    )
    return close_no or (same_date and book.tax_paise > 0)


def _period_bounds(period_start: datetime.date) -> tuple[datetime.date, datetime.date]:
    first = period_start.replace(day=1)
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return first, nxt - datetime.timedelta(days=1)


def _is_timing(book: Invoice, period_start: datetime.date) -> bool:
    """An invoice too recent for the supplier to have reported it yet.

    GSTR-2B for a month carries what suppliers filed by the 11th of the next
    month; an invoice dated late in the period is often simply not filed yet.
    Anything dated before the period started is not explained by that -- it
    should have appeared already -- so it is called a genuine mismatch.
    """
    if book.invoice_date is None:
        return False
    first, _last = _period_bounds(period_start)
    return book.invoice_date >= first


def _label(inv: Invoice) -> str:
    who = inv.supplier_name or inv.gstin or "supplier"
    return f"{who} ({inv.gstin})" if inv.supplier_name and inv.gstin else who


def _itc_for(book: Invoice, portal: Invoice) -> tuple[ItcStatus, int, int]:
    """(status, eligible, ineligible) for a book row matched to a portal row.

    The credit is the smaller of what was booked and what the supplier reported
    per head -- you cannot claim more than the portal shows, and you should not
    claim more than you booked.
    """
    credit = sum(min(getattr(book, h), getattr(portal, h)) for h in TAX_HEADS) * book.sign
    if blocked_reason(book):
        return ItcStatus.BLOCKED, 0, credit
    if not portal.itc_available:
        return ItcStatus.NOT_ELIGIBLE, 0, credit
    return ItcStatus.ELIGIBLE, credit, 0


# ---------------------------------------------------------------------------
# The reconciliation
# ---------------------------------------------------------------------------


def reconcile(
    book_rows: list[Invoice],
    portal_rows: list[Invoice],
    *,
    period_start: datetime.date,
    other_periods: dict[tuple[str, str], datetime.date] | None = None,
    claimed_elsewhere: dict[tuple[str, str], datetime.date] | None = None,
) -> Reconciliation:
    """Compare one GSTIN's purchase register with its GSTR-2B for one period.

    ``other_periods`` maps an invoice to the month of a *different* GSTR-2B it
    appears in, and ``claimed_elsewhere`` to the month of a different
    reconciliation that already took its credit. The first turns "missing" into
    "wrong period"; the second stops a credit being taken twice.
    """
    other_periods = other_periods or {}
    claimed_elsewhere = claimed_elsewhere or {}
    matches: list[Match] = []

    portal_by_key: dict[tuple[str, str], Invoice] = {}
    alias: dict[tuple[str, str], tuple[str, str]] = {}  # original number -> amended key
    for p in portal_rows:
        if p.section in (Section.IMPG, Section.ISD):
            matches.append(_portal_credit(p))
            continue
        key = p.key
        if key not in portal_by_key:
            portal_by_key[key] = p
        if p.original_no:
            alias[(normalise_gstin(p.gstin), normalise_invoice_no(p.original_no))] = key
    used_portal: set[tuple[str, str]] = set()
    seen_book: set[tuple[str, str]] = set()
    unresolved: list[Invoice] = []

    for b in book_rows:
        gstin = normalise_gstin(b.gstin)

        if b.rcm:
            matches.append(_rcm(b))
            continue

        if not gstin or not is_valid_gstin(gstin):
            matches.append(
                Match(
                    kind=MatchKind.INVALID_GSTIN,
                    book=b,
                    portal=None,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause="The supplier GSTIN is missing or not a valid GSTIN."
                    if not gstin
                    else f"{gstin} is not a valid GSTIN (format or check character).",
                    action=f"Correct the GSTIN on invoice {b.invoice_no} from {_label(b)}; "
                    "if the supplier is unregistered, mark it reverse charge.",
                )
            )
            continue

        key = (gstin, normalise_invoice_no(b.invoice_no))
        if key in seen_book:
            matches.append(
                Match(
                    kind=MatchKind.DUPLICATE,
                    book=b,
                    portal=None,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause="The same supplier and invoice number is already in the register.",
                    action=f"Check whether invoice {b.invoice_no} from {_label(b)} was "
                    "entered twice, and delete one.",
                )
            )
            continue
        seen_book.add(key)

        if key in claimed_elsewhere:
            used_portal.add(key)  # its 2B row is accounted for, not "unbooked"
            when = claimed_elsewhere[key].strftime("%B %Y")
            matches.append(
                Match(
                    kind=MatchKind.DUPLICATE,
                    book=b,
                    portal=None,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause=f"The credit on this invoice was already taken in {when}.",
                    action=f"Do not claim invoice {b.invoice_no} from {_label(b)} again; "
                    f"take it out of this register.",
                )
            )
            continue

        primary = key if key in portal_by_key else alias.get(key)
        portal = portal_by_key.get(primary) if primary else None
        if portal is None:
            unresolved.append(b)
            continue

        used_portal.add(primary)
        diffs = _differences(b, portal)
        if not diffs and portal.rcm:
            matches.append(
                Match(
                    kind=MatchKind.RCM,
                    book=b,
                    portal=portal,
                    itc_status=ItcStatus.RCM_ON_PAYMENT,
                    eligible_paise=0,
                    ineligible_paise=0,
                    cause="GSTR-2B marks this as reverse charge: we pay the tax, "
                    "and claim it back after paying.",
                    action=f"Pay reverse-charge GST on invoice {b.invoice_no} from "
                    f"{_label(b)} before claiming the credit.",
                )
            )
            continue
        if diffs and abs(b.tax_paise - portal.tax_paise) <= TOLERANCE_PAISE and "taxable_paise" not in diffs:
            matches.append(
                Match(
                    kind=MatchKind.TAX_HEAD_MISMATCH,
                    book=b,
                    portal=portal,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause="The total tax matches but the heads differ (IGST against "
                    "CGST/SGST) -- usually a place-of-supply error.",
                    action=f"Check the place of supply on invoice {b.invoice_no} from "
                    f"{_label(b)}; correct our entry or ask the supplier to amend.",
                    differences=diffs,
                )
            )
        elif diffs:
            matches.append(
                Match(
                    kind=MatchKind.AMOUNT_MISMATCH,
                    book=b,
                    portal=portal,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause="Amounts differ from GSTR-2B on: "
                    + ", ".join(h.removesuffix("_paise") for h in diffs)
                    + ".",
                    action=f"Compare invoice {b.invoice_no} from {_label(b)} with the "
                    "supplier's copy; correct our entry or ask the supplier to amend.",
                    differences=diffs,
                )
            )
        else:
            status, eligible, ineligible = _itc_for(b, portal)
            matches.append(
                Match(
                    kind=MatchKind.MATCHED,
                    book=b,
                    portal=portal,
                    itc_status=status,
                    eligible_paise=eligible,
                    ineligible_paise=ineligible,
                    cause=blocked_reason(b)
                    if status is ItcStatus.BLOCKED
                    else (
                        "GSTR-2B says ITC is not available"
                        + (f" (reason {portal.itc_reason})" if portal.itc_reason else "")
                        + "."
                    )
                    if status is ItcStatus.NOT_ELIGIBLE
                    else "",
                    action="",
                )
            )

    # Book rows with no exact counterpart: try a near match before giving up.
    free_portal = {k: p for k, p in portal_by_key.items() if k not in used_portal}
    for b in unresolved:
        candidate_key = next(
            (k for k, p in free_portal.items() if _looks_like_same_invoice(b, p)), None
        )
        if candidate_key is not None:
            p = free_portal.pop(candidate_key)
            used_portal.add(candidate_key)
            matches.append(
                Match(
                    kind=MatchKind.POSSIBLE_MATCH,
                    book=b,
                    portal=p,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause=f"Our invoice number {b.invoice_no} is close to GSTR-2B's "
                    f"{p.invoice_no} for the same supplier and tax.",
                    action=f"Confirm invoice {b.invoice_no} from {_label(b)} is "
                    f"{p.invoice_no} on the portal, and fix the number in the books.",
                )
            )
            continue

        elsewhere = other_periods.get(b.key)
        if elsewhere is not None:
            when = elsewhere.strftime("%B %Y")
            matches.append(
                Match(
                    kind=MatchKind.WRONG_PERIOD,
                    book=b,
                    portal=None,
                    itc_status=ItcStatus.NOT_ELIGIBLE,
                    eligible_paise=0,
                    ineligible_paise=b.tax_paise * b.sign,
                    cause=f"Not in this month's GSTR-2B, but it appears in {when}'s.",
                    action=f"Claim invoice {b.invoice_no} from {_label(b)} in the "
                    f"{when} return (check it was not already claimed).",
                )
            )
            continue

        timing = _is_timing(b, period_start)
        matches.append(
            Match(
                kind=MatchKind.MISSING_IN_2B,
                book=b,
                portal=None,
                itc_status=ItcStatus.NOT_ELIGIBLE,
                eligible_paise=0,
                ineligible_paise=b.tax_paise * b.sign,
                cause="Not in this month's GSTR-2B. The supplier may not have filed "
                "their return yet."
                if timing
                else "Not in GSTR-2B although dated before this period -- it should "
                "already have appeared. Check an earlier month, or whether the supplier filed.",
                action=f"Follow up with {_label(b)} -- invoice {b.invoice_no} not yet "
                "reflected in GSTR-2B.",
                timing=timing,
            )
        )

    for p in free_portal.values():
        matches.append(
            Match(
                kind=MatchKind.MISSING_IN_BOOKS,
                book=None,
                portal=p,
                itc_status=ItcStatus.NOT_ELIGIBLE,
                eligible_paise=0,
                ineligible_paise=0,
                cause="On the portal but not in the purchase register.",
                action=f"Check for invoice {p.invoice_no} from {_label(p)}: book it if "
                "it is ours, or ignore it if it was reported against our GSTIN in error.",
            )
        )

    return Reconciliation(matches=matches, summary=_summarise(matches))


def _portal_credit(p: Invoice) -> Match:
    """An import or ISD credit: on the portal only, never in a purchase register."""
    is_import = p.section is Section.IMPG
    ok = p.itc_available
    return Match(
        kind=MatchKind.IMPORT if is_import else MatchKind.ISD_CREDIT,
        book=None,
        portal=p,
        itc_status=ItcStatus.ELIGIBLE if ok else ItcStatus.NOT_ELIGIBLE,
        eligible_paise=p.tax_paise * p.sign if ok else 0,
        ineligible_paise=0 if ok else p.tax_paise * p.sign,
        cause="Import of goods per the bill of entry -- verify against the books."
        if is_import
        else "Credit distributed by an Input Service Distributor -- verify the ISD invoice.",
        action=f"Confirm {'bill of entry' if is_import else 'ISD distribution'} "
        f"{p.invoice_no} against the books before claiming.",
    )


def _rcm(b: Invoice) -> Match:
    return Match(
        kind=MatchKind.RCM,
        book=b,
        portal=None,
        itc_status=ItcStatus.RCM_ON_PAYMENT,
        eligible_paise=0,
        ineligible_paise=0,
        cause="Reverse charge: we pay this tax, and claim it back after paying.",
        action=f"Pay reverse-charge GST on invoice {b.invoice_no} from {_label(b)} "
        "before claiming the credit.",
    )


def _summarise(matches: list[Match]) -> Summary:
    counts: dict[str, int] = {k.value: 0 for k in MatchKind}
    eligible = blocked = ineligible = rcm = unclaimed = 0
    for m in matches:
        counts[m.kind.value] += 1
        eligible += m.eligible_paise
        if m.itc_status is ItcStatus.BLOCKED:
            blocked += m.ineligible_paise
        elif m.itc_status is ItcStatus.NOT_ELIGIBLE:
            ineligible += m.ineligible_paise
        if m.kind is MatchKind.RCM and m.book is not None:
            rcm += m.book.tax_paise * m.book.sign
        if m.kind is MatchKind.MISSING_IN_BOOKS and m.portal is not None:
            unclaimed += m.portal.tax_paise * m.portal.sign
    return Summary(
        counts=counts,
        eligible_paise=eligible,
        blocked_paise=blocked,
        ineligible_paise=ineligible,
        rcm_liability_paise=rcm,
        unclaimed_in_2b_paise=unclaimed,
    )
