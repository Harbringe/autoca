"""Indian tax identifiers: what a well-formed one looks like.

Format checks only. Whether a GSTIN is *active* is a question for the GST
portal, and this module does not call anything. What it can do is refuse the
ones that cannot possibly be right, which is most typos -- and it can do it at
the API boundary, where the person who typed it is still looking at the screen.
"""

from __future__ import annotations

import re

PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def is_valid_pan(value: str) -> bool:
    return bool(PAN_RE.match((value or "").strip().upper()))


def gstin_check_character(first_fourteen: str) -> str:
    """The fifteenth character of a GSTIN, from the first fourteen.

    GSTN's published algorithm: each character's index in the base-36 alphabet
    is multiplied by a factor alternating 1, 2, 1, 2...; each product is reduced
    as ``quotient + remainder`` on division by 36; the sum modulo 36 is
    subtracted from 36, modulo 36 again, and looked up in the same alphabet.
    """
    total = 0
    for position, char in enumerate(first_fourteen):
        factor = 2 if position % 2 else 1
        product = _ALPHABET.index(char) * factor
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(value: str) -> bool:
    """Shape and check character. The embedded PAN must itself be well-formed."""
    value = (value or "").strip().upper()
    if not GSTIN_RE.match(value):
        return False
    if not is_valid_pan(value[2:12]):
        return False
    state = int(value[:2])
    if not (1 <= state <= 38 or state in (97, 99)):
        return False
    return gstin_check_character(value[:14]) == value[14]
