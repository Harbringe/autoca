"""Taking identifiers out of text before it goes anywhere.

One implementation, used everywhere: the classifier masks a narration with this
before a model sees it, and the logging layer masks every record with it before
a line is written. The architecture is explicit that these must be the same
function -- two implementations drift, and the one that drifts is always the
one nobody is looking at.

What is masked, and why each is regex-detectable with high reliability:

* **PAN** -- ten characters in a fixed shape (``AAAAA9999A``), with the fourth
  letter drawn from a small set of holder types.
* **GSTIN** -- fifteen characters: a two-digit state code, a PAN, an entity
  digit, ``Z``, and a check character.
* **Aadhaar** -- twelve digits, often grouped in fours.
* **Account numbers** -- runs of 9 to 18 digits. Bank references in narrations
  are digit runs too, and they are masked as well; a reference number is
  identifying enough to be worth removing and useless for classification.
* **IFSC** -- four letters, a zero, six alphanumerics.
* **Phone numbers** -- ten digits starting 6-9, optionally ``+91`` prefixed.
* **Card numbers** -- 13 to 19 digits with optional separators, and the
  ``XX 1234`` / ``400000****0000`` shapes banks print.
* **Email addresses**, and UPI addresses (``name@handle``).

Order matters: the wider pattern first, so a GSTIN is replaced whole rather than
having its embedded PAN replaced first and the rest left as noise. Each match is
replaced with a *typed* placeholder -- ``<GSTIN>``, ``<ACCT>`` -- because the
kind of thing that was there is useful to a classifier and to a person reading a
log, while the value is not.

What is *not* masked here: names. A person's name is not regex-detectable, and
the classifier handles it a different way -- known parties are swapped for their
alias token, and everything else about a counterparty that a model needs is its
channel and shape. See ``classify/pseudonymise.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Applied in this order. Each entry is (placeholder, pattern).
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("<EMAIL>", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # A UPI address, name@handle: an e-mail shape with no dotted domain.
    ("<UPI_ID>", re.compile(r"(?<![\w.%+-])[A-Za-z0-9._-]{2,}@[A-Za-z][A-Za-z0-9]{1,}\b")),
    # 22AAAAA0000A1Z5 -- state code, PAN, entity number, Z, check character.
    ("<GSTIN>", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    ("<PAN>", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b")),
    ("<IFSC>", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    # Card numbers as banks print them: grouped in fours, or partly starred.
    # A bare run of digits is *not* taken for a card -- a fifteen-digit account
    # number is far more common in a narration than a fifteen-digit card, and
    # both are masked either way; only the label would differ.
    (
        "<CARD>",
        re.compile(
            r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,7}\b|\b\d{4,6}\*{2,8}\d{2,4}\b|\bXX\s?\d{4}\b"
        ),
    ),
    # Before Aadhaar: +91 and ten digits is twelve digits, which is Aadhaar's
    # length, and the prefix says which one it is.
    ("<PHONE>", re.compile(r"(?<!\d)(?:\+91[ -]?|0)?[6-9]\d{9}(?!\d)")),
    # 1234 5678 9012, with or without the spaces.
    ("<AADHAAR>", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b")),
    # Account numbers and bank references: any remaining long digit run.
    ("<ACCT>", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),
)


@dataclass(frozen=True)
class Masked:
    """The masked text, and what was taken out of it, by kind."""

    text: str
    #: Placeholder -> how many were replaced. For the audit trail: a caller can
    #: record that a narration went out with two account numbers removed
    #: without recording the numbers.
    removed: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.removed)


def mask(text: str) -> Masked:
    """Replace every identifier in ``text`` with a typed placeholder."""
    if not text:
        return Masked(text=text or "")
    removed: dict[str, int] = {}
    for placeholder, pattern in PATTERNS:
        text, count = pattern.subn(placeholder, text)
        if count:
            removed[placeholder] = removed.get(placeholder, 0) + count
    return Masked(text=text, removed=removed)


def mask_text(text: str) -> str:
    """The masked string alone, for callers that do not need the tally."""
    return mask(text).text
