"""Business and person names: one way of writing them, and a way of telling whether two spellings are the same business.

Names reach the books in every case and spelling a document can print: ``SHRI NARAYAN TRADING CO.``, ``Gajraj trading company``,
``S.B.H DRYFRUITS``. ``normalise`` writes them the one way so lists and forms look the same; ``same_business`` is how a file is
told to be the client's own (its name on one side of an invoice) when no GSTIN is on record to say so. Neither changes what is
stored for a name somebody typed on purpose: a word that already mixes cases (``McDonald``, ``iPhone``) is left as written.
"""

from __future__ import annotations

import re

#: Kept in capitals wherever they appear.
_KEEP_UPPER = frozenset(
    {"LLP", "HUF", "OPC", "GST", "TDS", "MSME", "LLC", "HP", "BP", "UP", "MP", "AP", "II", "III", "IV", "ATM", "SBI", "HDFC", "ICICI", "LIC", "NTPC", "ONGC", "TCS", "IBM"}
)
#: Small words written in lower case unless they start the name.
_SMALL = frozenset({"and", "of", "the", "for", "in", "at", "on", "to"})
#: Dots and spaces in an initialism like ``S.B.H`` or ``M/S``.
_INITIALS = re.compile(r"^(?:[A-Za-z]\.){1,}[A-Za-z]?\.?$")
_WORD = re.compile(r"[^\s]+")

#: Said once, in any case, on a business name; they say what kind of firm it is, not which one.
_FORM_WORDS = frozenset(
    {"pvt", "private", "ltd", "limited", "llp", "co", "company", "corp", "corporation", "inc", "the", "and", "m", "s", "ms", "mrs", "mr", "shri", "shree", "sri"}
)


def _case_part(part: str) -> str:
    if not part:
        return part
    if len(part) == 1:
        return part.upper()
    return part[0].upper() + part[1:].lower()


def _word(word: str, first: bool) -> str:
    stripped = word.strip(".,()&")
    if word == "&":
        return word
    if _INITIALS.match(word):
        return word.upper()
    # Mixed case on purpose (McDonald, iPhone): leave it.
    if any(c.islower() for c in stripped) and any(c.isupper() for c in stripped[1:]):
        return word
    if stripped.upper() in _KEEP_UPPER:
        return word.upper()
    if not first and stripped.lower() in _SMALL:
        return word.lower()
    if any(c.isdigit() for c in word):
        return word.upper() if word.isupper() else word
    # Hyphenated, slashed and apostrophe names: each part gets its own capital.
    return re.sub(r"[A-Za-z]+", lambda m: _case_part(m.group(0)), word)


def normalise(text: str) -> str:
    """The one way a name is written: spaces collapsed, ``Title Case``, initialisms and ``LLP`` and the like in capitals."""
    words = _WORD.findall(str(text or ""))
    return " ".join(_word(w, i == 0) for i, w in enumerate(words))


def tokens(text: str) -> frozenset[str]:
    """The words that say which business this is: lower case, no punctuation, none of the 'Pvt Ltd' kind."""
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return frozenset(w for w in words if w not in _FORM_WORDS and len(w) > 1 or w.isdigit())


def same_business(a: str, b: str) -> bool:
    """Whether two spellings name the same business: one's identifying words all appear in the other, and there are at least two.

    ``SHRI NARAYAN TRADING CO.`` and ``Shri Narayan Trading Company Loha`` are the same; ``Shri Narayan Traders`` is not (one
    differs), and neither is ``Shri Padmavati Trading Co`` (only 'trading' is shared). Evidence for a suggestion, never proof.
    """
    left, right = tokens(a), tokens(b)
    if len(left) < 2 or len(right) < 2:
        return False
    small, large = (left, right) if len(left) <= len(right) else (right, left)
    return small <= large
