"""Reading the structure hidden in a bank narration line.

A narration is not free text. Banks build it from a template, and the template
says what each slash-separated field means:

    UPI/P2M/100000000001/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD
    ^   ^   ^            ^                     ^      ^
    |   |   reference    counterparty          remark counterparty's bank
    |   person-to-merchant
    channel

Pulling those apart before matching is what separates a classifier that works
from one that looks like it works. Matched as raw substrings, two narrations
differing only in their reference number are different strings, so every single
UPI payment needs its own rule and the rule table grows without ever converging.
Matched on the *counterparty*, one rule covers every payment to that payee
forever. That is the whole difference between a tool a firm keeps using and one
they abandon in week three.

It also decides what may be sent to a model later. The reference numbers and
account fragments are the identifying parts; the counterparty and channel are
what a classifier actually needs. Separating them here is what makes it possible
to send the second without the first.

Formats below are from real Axis savings statements. Other banks use the same
channel prefixes with their own field order, which is why each pattern is
anchored to its channel and an unrecognised line degrades to
``channel=UNKNOWN`` with the raw text intact rather than being force-fitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: How alike two spellings of a name must be to be treated as the same person.
#: See ``_looks_like_self`` for why this is a ratio and not an equality test.
SELF_NAME_SIMILARITY = 0.85


class Channel:
    """How the money moved. The first field of almost every narration."""

    UPI = "UPI"
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"
    #: In-bank transfer initiated from the mobile app or a branch.
    TRANSFER = "TRANSFER"
    CHEQUE = "CHEQUE"
    CARD = "CARD"
    CASH = "CASH"
    #: Interest the bank paid or collected on the account itself.
    INTEREST = "INTEREST"
    #: Sweep to or from a linked deposit.
    SWEEP = "SWEEP"
    #: Tax paid through internet banking.
    TAX = "TAX"
    #: Demand draft, PPF, and other branch instruments.
    INSTRUMENT = "INSTRUMENT"
    FEE = "FEE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class NarrationFacts:
    """What could be read out of one narration line."""

    raw: str
    channel: str = Channel.UNKNOWN
    #: The other side of the transaction, as the bank spelled it. The single
    #: most useful field: it is what a rule should match on.
    counterparty: str = ""
    #: Bank-assigned transaction reference. Unique per transaction, therefore
    #: useless for matching and identifying enough to be worth isolating.
    reference: str = ""
    #: The payer's own note, where the channel carries one ("Meter", "Hotel").
    remark: str = ""
    counterparty_bank: str = ""
    #: Cheque number, card last-four, or similar instrument identifier.
    instrument: str = ""
    #: True when both sides of the transfer are the account holder's own
    #: accounts. These are contra entries, not income or expenditure, and
    #: booking them as either overstates both.
    is_self_transfer: bool = False

    @property
    def is_recognised(self) -> bool:
        return self.channel != Channel.UNKNOWN

    @property
    def match_key(self) -> str:
        """The stable part of the narration, for rule matching and grouping.

        Everything a rule should key on and nothing that changes per
        transaction. Two payments to the same payee produce the same key.
        """
        return normalise(self.counterparty or self.raw)


def normalise(text: str) -> str:
    """Case-folded, punctuation- and space-free form used for all comparisons.

    Spaces are removed rather than collapsed, and that is the important part.
    A narration is wrapped to the column width in the PDF, and the wrap lands
    mid-token as readily as it lands on a space:

        UPI/P2M/100000000004/GODAVARI_RESTAU
        RANT_ /Hotel/YES BANK LIMITED YBS

    Rejoining that is a coin flip -- a space is right for a payee name split at
    its space, wrong for a merchant name split mid-word -- and getting it wrong
    means the same payee produces two different match keys. Discarding spaces
    entirely makes the question moot, and incidentally makes the bank's own
    inconsistency (``Arjun Pratap Nair`` in one row, ``ArjunPratapNair``
    in the next) disappear as well.

    This is for matching only. The narration is stored as the bank wrote it.
    """
    return re.sub(r"[^A-Z0-9]+", "", (text or "").upper())


def _clean(field: str) -> str:
    return re.sub(r"\s+", " ", (field or "").strip(" /")).strip()


# ---------------------------------------------------------------------------
# Channel patterns
#
# Ordered. The first match wins, so anything narrow enough to be mistaken for a
# broader pattern comes first.
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # SB:900000000000001:Int.Pd:01-04-2025 to 30-06-2025
    (Channel.INTEREST, re.compile(r"^SB:(?P<account>\d+):Int\.(?P<kind>Pd|Coll)", re.I)),
    # Sweep/VO000000012345678/19000000000001
    (Channel.SWEEP, re.compile(r"^(?P<kind>SWEEP|AUTOSWEEP|REV SWEEP)\s*[/:](?P<reference>[^/]*)", re.I)),
    # CreditCard Payment XX 0000 Ref#GFYPDNWLV474ZO
    (
        Channel.CARD,
        re.compile(r"^CreditCard\s+Payment\s+XX\s*(?P<instrument>\w+)(?:\s+Ref#(?P<reference>\S+))?", re.I),
    ),
    # CRD-PMNT-400000****0000  /  CREDIT BALANCE REFUND 4000000000000000
    (Channel.CARD, re.compile(r"^CRD-PMNT-(?P<instrument>\S+)", re.I)),
    (Channel.CARD, re.compile(r"^CREDIT\s+BALANCE\s+REFUND\s*(?P<instrument>\S+)?", re.I)),
    # INB/100000009/INTERNET TAX PAYMENT/
    (
        Channel.TAX,
        re.compile(r"^INB/(?P<reference>[^/]*)/(?P<counterparty>[^/]*TAX[^/]*)", re.I),
    ),
    # UPI/P2A/100000000003/SURESH KIRAN MENON/Meter/HDFC BANK LTD
    (
        Channel.UPI,
        re.compile(
            r"^UPI/(?P<kind>P2A|P2M|P2V)/(?P<reference>[^/]*)/(?P<counterparty>[^/]*)"
            r"(?:/(?P<remark>[^/]*))?(?:/(?P<counterparty_bank>[^/]*))?",
            re.I,
        ),
    ),
    # IMPS/P2A/100000000002/ArjunPratapNair/X000001/HDFCBANKLTD/
    (
        Channel.IMPS,
        re.compile(
            r"^IMPS/(?P<kind>P2A|P2M)?/?(?P<reference>[^/]*)/(?P<counterparty>[^/]*)"
            r"(?:/(?P<remark>[^/]*))?(?:/(?P<counterparty_bank>[^/]*))?",
            re.I,
        ),
    ),
    # NEFT/MB/AXOMB10000000001/Arjun Pratap Nair/HDFC BANK/OTHERS
    (
        Channel.NEFT,
        re.compile(
            r"^NEFT/(?:MB/)?(?P<reference>[^/]*)/(?P<counterparty>[^/]*)"
            r"(?:/(?P<counterparty_bank>[^/]*))?(?:/(?P<remark>[^/]*))?",
            re.I,
        ),
    ),
    # RTGS/HDFCR50000000000000001/DR ARJUN PRATAP NAI/HDFC BANK///Self//OP
    (
        Channel.RTGS,
        re.compile(
            r"^RTGS/(?P<reference>[^/]*)/(?:DR\s+|CR\s+)?(?P<counterparty>[^/]*)"
            r"(?:/(?P<counterparty_bank>[^/]*))?(?P<remark>.*)$",
            re.I,
        ),
    ),
    # MOB/TPFT/PRIYA ARJUN N/900000000000002
    (
        Channel.TRANSFER,
        re.compile(r"^MOB/(?:TPFT|TPT)/(?P<counterparty>[^/]*)(?:/(?P<remark>[^/]*))?", re.I),
    ),
    # TRF/318/MEERA PRATAP /Meera Pratap
    (
        Channel.TRANSFER,
        re.compile(r"^TRF/(?P<reference>\d*)/(?P<counterparty>[^/]*)(?:/(?P<remark>[^/]*))?", re.I),
    ),
    # BRN-CLG-CHQ PAID TO Wipro Ge Health/HONGKONG and S
    (
        Channel.CHEQUE,
        re.compile(
            r"^BRN-CLG-CHQ\s+PAID\s+TO\s+(?P<counterparty>[^/]*)(?:/(?P<counterparty_bank>.*))?", re.I
        ),
    ),
    # Clg/WIPRO GE HEALTHCARE PVT/HONGKONG and S
    (
        Channel.CHEQUE,
        re.compile(r"^Clg/(?P<counterparty>[^/]*)(?:/(?P<counterparty_bank>.*))?", re.I),
    ),
    # DD ISSUED/DIBG/Medical officer of Health, CMC, N
    (
        Channel.INSTRUMENT,
        re.compile(r"^DD\s+ISSUED/(?P<reference>[^/]*)/(?P<counterparty>.*)", re.I),
    ),
    # IPPF/0001PPF0000000000001/900000000000001
    (
        Channel.INSTRUMENT,
        re.compile(r"^(?P<counterparty>IPPF|PPF|RD|TD)/(?P<reference>[^/]*)", re.I),
    ),
    (Channel.CASH, re.compile(r"^(?P<counterparty>CWDR|ATM-CASH|CASH\s+DEP)", re.I)),
    (Channel.FEE, re.compile(r"^(?P<counterparty>.*(?:CHARGES?|CHRG|FEE|GST)\b.*)$", re.I)),
]

#: Markers a bank puts in a narration when both sides are the same customer.
_SELF_MARKERS = ("//SELF//", "/SELF/", " SELF ", "SELF TRANSFER")

#: Only these channels can be a transfer between the client's own accounts.
#: Interest credited by the bank mentions the account number too, and is income,
#: not a contra entry -- treating it as one would drop it out of the books.
_TRANSFERABLE = frozenset(
    {Channel.UPI, Channel.NEFT, Channel.RTGS, Channel.IMPS, Channel.TRANSFER, Channel.UNKNOWN}
)


def analyse(narration: str, account_holder: str = "", own_accounts=()) -> NarrationFacts:
    """Read what structure there is in ``narration``.

    ``account_holder`` and ``own_accounts`` let the analyser spot a transfer
    between the client's own accounts, which is a contra entry rather than
    income or expenditure. Booking those either way inflates both sides of the
    client's books, and they are common enough in practice -- the sample
    statement moves money to and from the holder's own HDFC account five times
    in one year -- that missing them is not a rounding error.
    """
    raw = re.sub(r"\s+", " ", (narration or "").strip())

    for channel, pattern in _PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        groups = {k: _clean(v) for k, v in (match.groupdict() or {}).items() if v}
        counterparty = groups.get("counterparty", "")

        instrument = groups.get("instrument", "")
        counterparty = _name_the_party(channel, counterparty, instrument, groups)

        return NarrationFacts(
            raw=raw,
            channel=channel,
            counterparty=counterparty,
            reference=groups.get("reference", ""),
            remark=groups.get("remark", ""),
            counterparty_bank=groups.get("counterparty_bank", ""),
            instrument=instrument,
            is_self_transfer=(
                channel in _TRANSFERABLE
                and _looks_like_self(raw, counterparty, account_holder, own_accounts)
            ),
        )

    return NarrationFacts(
        raw=raw,
        is_self_transfer=_looks_like_self(raw, "", account_holder, own_accounts),
    )


def _name_the_party(channel: str, counterparty: str, instrument: str, groups: dict) -> str:
    """Give channels that have no named payee a stable party name anyway.

    A card repayment, a sweep and an interest credit all have a counterparty in
    accounting terms -- the card account, the linked deposit, the bank -- but
    the narration names none of them. Without a name here every one of these
    would land in the review queue forever, and they are the rows a firm least
    wants to look at.
    """
    if channel == Channel.CARD:
        digits = re.sub(r"\D", "", instrument or "")
        return f"Credit Card {digits[-4:]}" if digits else "Credit Card"
    if channel == Channel.INTEREST:
        return "Interest Paid" if groups.get("kind", "").lower() == "pd" else "Interest Collected"
    if channel == Channel.SWEEP:
        return "Sweep"
    return counterparty


def _looks_like_self(raw: str, counterparty: str, account_holder: str, own_accounts) -> bool:
    upper = raw.upper()
    if any(marker in upper for marker in _SELF_MARKERS):
        return True
    if any(str(account) and str(account) in raw for account in own_accounts):
        return True
    if not account_holder or not counterparty:
        return False

    # Banks run the holder's name together (MohanDeepakRao) as readily as
    # they space it, so compare on the letters alone.
    holder = re.sub(r"[^A-Z]", "", account_holder.upper())
    other = re.sub(r"[^A-Z]", "", counterparty.upper())
    if len(holder) < 8 or len(other) < 8:
        return False

    # Approximate, not exact, because a bank does not spell its own customer's
    # name consistently. One statement carries the holder as MOHAN DEEPAK RAO
    # in the header, Mohan Deepak Rao in a NEFT narration, and truncates it to
    # MOHAN DEEPAK RA in an RTGS one. Exact or prefix
    # matching misses two of those three and books a contra entry as income.
    #
    # The threshold sits where a spelling variant of one name still matches and
    # a relative sharing a surname does not -- VIKRAM ARJUN NAIR against
    # ARJUN PRATAP NAIR scores well below it. That gap matters: those are
    # different people, and one is a contra while the other is drawings.
    return SequenceMatcher(None, holder, other).ratio() >= SELF_NAME_SIMILARITY
