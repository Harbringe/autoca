"""How much a payee's history justifies placing its next payment without asking.

A rule learned from one click is a hypothesis, not a pattern. How far to trust it depends on three proportions, none of them a fixed count:

* **Consistency** -- of the decisions a person made for this payee (and direction), how large a share went to the ledger the rule names.
  Judged by the Wilson lower bound, so a small sample earns little and a long unbroken run earns a lot.
* **Specificity** -- how well the name picks out one counterparty. A multi-word or GSTIN-backed name starts with some trust. A bare first
  name shared by many of the client's payees (ABDUL, ABDULLA, ADBUL) starts with none: it may be several different people.
* **Base rate** -- how much of the client's money in that direction goes to the same ledger anyway. If 70% of receipts are Sales, a rule
  that says Sales has told us little, so it earns less than the same record against a ledger few rows use.

Pure functions, no database, so the whole design can be tested with made-up histories.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt

#: z for a one-sided ~84% bound: the share we are about 84% sure the true consistency is at least.
_Z = 1.0

#: At or above these the placement is trusted to act alone / is worth suggesting (same as the review bands).
ASSERT_AT = 0.90
SUGGEST_AT = 0.75


def wilson_lower(agree: float, total: float) -> float:
    """The lower bound of the share ``agree/total``, which is small when ``total`` is small."""
    if total <= 0:
        return 0.0
    p = min(max(agree / total, 0.0), 1.0)
    z2 = _Z * _Z
    centre = p + z2 / (2 * total)
    margin = _Z * sqrt((p * (1 - p) + z2 / (4 * total)) / total)
    return max(0.0, (centre - margin) / (1 + z2 / total))


def name_specificity(counterparty: str, payees: Counter[str] | None = None, *, has_gstin: bool = False) -> float:
    """0..1 -- how well this payee name picks out one counterparty among the client's payees.

    ``payees`` counts, for the client, how many distinct payee names begin with each first word (lower-cased).
    """
    if has_gstin:
        return 1.0
    words = counterparty.split()
    if not words:
        return 0.0
    if len(words) >= 2:
        return 0.8
    shared = (payees or Counter()).get(words[0].lower(), 1) - 1
    # Alone in its first word: plausibly one business. Sharing it with others: a first name many people have.
    return 0.5 if shared <= 0 else max(0.0, 0.3 - 0.05 * shared)


def first_word_counts(counterparties) -> Counter[str]:
    """For every first word, how many distinct payee names begin with it."""
    seen = {" ".join(c.lower().split()) for c in counterparties if c and c.strip()}
    return Counter(name.split()[0] for name in seen)


@dataclass(frozen=True)
class Evidence:
    """What a payee's decided rows say about one ledger."""

    agree: int  # decisions that went to this ledger
    total: int  # decisions of any ledger for this payee and direction
    specificity: float = 0.5
    base_rate: float = 0.0  # share of the client's rows in this direction already in this ledger


def confidence(e: Evidence) -> float:
    """0..1 trust that the next payment from/to this payee belongs in the ledger. See the module note for what goes into it."""
    # A specific name carries up to six imagined agreeing decisions in its favour; a common first name carries none.
    prior = round(6 * e.specificity)
    lower = wilson_lower(e.agree + prior, e.total + prior)
    base = min(max(e.base_rate, 0.0), 0.95)
    return lower ** (1 + base)


def verdict(score: float) -> str:
    """What the score earns: place on its own, suggest, or leave to a person."""
    if score >= ASSERT_AT:
        return "place"
    if score >= SUGGEST_AT:
        return "suggest"
    return "ask"
