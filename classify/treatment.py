"""What it means to have decided how a transaction is treated.

An Indian bookkeeping decision is not one field. Placing a payment says four
things at once:

* which **ledger head** it belongs to -- Office Supplies, Rent, Professional
  Fees;
* which **party** it was with, where there is an identifiable one. The
  requirements document is explicit that a ledger head alone is not usable
  output: the ledger-and-party distinction is standard, and dropping it means a
  firm cannot answer "how much did we pay this party this year" without
  re-reading narrations;
* whether **reverse charge** applies, making the client liable for the GST
  rather than the party -- goods transport, legal services, purchases from
  unregistered dealers;
* which **TDS section** applies, if the payment type crosses its threshold.

These travel together because they are learned together. The architecture is
specific about this: RCM and TDS treatments ride along in the memory row, so
"this party is reverse-charge" is decided once per client and then applied,
which is exactly the memory behaviour the requirements document asks for.

Carrying them as one object rather than four parameters is not tidiness. It is
what stops the learning loop from remembering the ledger and forgetting the rest
-- a bug that would look like it worked, right up to the point a return is
prepared from books missing half their reverse-charge entries.
"""

from __future__ import annotations

from dataclasses import dataclass


class TdsSection:
    """The sections a bank payment realistically triggers.

    Deliberately not exhaustive -- the Income Tax Act has dozens, and a firm
    that needs one not listed here should be able to type it. Stored as a plain
    string for that reason; these are the suggestions, not the schema.
    """

    SALARY = "192"
    INTEREST = "194A"
    CONTRACTOR = "194C"
    COMMISSION = "194H"
    RENT = "194I"
    PROFESSIONAL = "194J"
    PURCHASE_OF_GOODS = "194Q"

    CHOICES = [
        (SALARY, "192 -- Salary"),
        (INTEREST, "194A -- Interest other than securities"),
        (CONTRACTOR, "194C -- Payment to contractors"),
        (COMMISSION, "194H -- Commission or brokerage"),
        (RENT, "194I -- Rent"),
        (PROFESSIONAL, "194J -- Professional or technical fees"),
        (PURCHASE_OF_GOODS, "194Q -- Purchase of goods"),
    ]


@dataclass(frozen=True)
class Treatment:
    """One complete accounting decision about a transaction."""

    ledger: object
    party: object = None
    #: True when the client, as recipient, pays the GST instead of the party.
    rcm: bool = False
    #: Blank when no TDS applies. A section number, e.g. "194J".
    tds_section: str = ""

    def __post_init__(self):
        if self.ledger is None:
            raise ValueError(
                "A treatment needs a ledger head. Leaving a transaction "
                "unplaced is a separate state, not a treatment with a hole in it."
            )

    @property
    def is_taxed(self) -> bool:
        """True when this decision has a tax consequence beyond the ledger entry."""
        return self.rcm or bool(self.tds_section)

    def matches(self, other) -> bool:
        """True when ``other`` carries the same decision on all four counts."""
        if other is None:
            return False
        return (
            getattr(other, "ledger_id", None) == getattr(self.ledger, "pk", None)
            and getattr(other, "party_id", None) == getattr(self.party, "pk", None)
            and bool(getattr(other, "rcm", False)) == self.rcm
            and (getattr(other, "tds_section", "") or "") == self.tds_section
        )

    def as_fields(self) -> dict:
        """The four columns, for writing onto a rule or a classification."""
        return {
            "ledger": self.ledger,
            "party": self.party,
            "rcm": self.rcm,
            "tds_section": self.tds_section,
        }


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

#: At or above this, the system is asserting rather than suggesting, and the row
#: is eligible for one-click bulk approval.
HIGH_CONFIDENCE = 0.90

#: Below this, a suggestion is not worth making. The row goes to a person with
#: the evidence attached rather than with a guess in front of it -- a confident
#: wrong answer is worse than an honest "I don't know" in accounting, and the
#: requirements document says so directly.
REVIEW_ADVISED = 0.75


class ReviewBand:
    """How a suggestion should be presented, derived from its confidence.

    The review screen is sorted by this. That ordering is the whole reason the
    bands exist: it is what turns an hour of checking every row into minutes of
    checking the ones that need it.
    """

    HIGH = "HIGH"
    ADVISED = "ADVISED"
    JUDGEMENT = "JUDGEMENT"

    CHOICES = [
        (HIGH, "High confidence -- bulk approvable"),
        (ADVISED, "Review advised"),
        (JUDGEMENT, "Needs human judgement"),
    ]


def band_for(confidence: float) -> str:
    if confidence >= HIGH_CONFIDENCE:
        return ReviewBand.HIGH
    if confidence >= REVIEW_ADVISED:
        return ReviewBand.ADVISED
    return ReviewBand.JUDGEMENT
