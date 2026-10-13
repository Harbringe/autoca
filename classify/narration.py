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

Formats below are from real Axis, ICICI and SBI statements. Other banks use the same
channel prefixes with their own field order, which is why each pattern is
anchored to its channel and an unrecognised line degrades to
``channel=UNKNOWN`` with the raw text intact rather than being force-fitted.

Three rules keep this safe to extend:

* **A payee is only ever read from a field whose position is certain.** Where a bank's field order varies between rows (some UPI
  credits put the reference first, some put the payee first), the row gets its channel and no counterparty. A guessed payee would
  become a rule key, and one decision would then place unrelated rows.
* **The fallback gives a channel and hints, never a counterparty.** A line no pattern matches is still classed by its leading
  word (``ACH``, ``UPI``, ``POS``...), and the words it contains that name a purpose are reported as ``hints``.
* **Hints are a closed vocabulary.** They are canonical words (``DIVIDEND``, ``REFUND``, ``FUEL``...), never the text that matched,
  so they can go to a model even when the narration itself is withheld: no name can ride along in them.
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
    #: An ACH / NACH mandate: a debit or credit the payee's bank collects under a standing authority.
    MANDATE = "MANDATE"
    #: A debit-card swipe or an online card purchase at a merchant. Not a card *repayment* (that is CARD).
    POS = "POS"
    #: A utility or other bill paid through the bank's bill-payment service.
    BILL = "BILL"
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
    #: Canonical purpose words found in the narration (see ``_HINTS``). A closed vocabulary, so safe to send even when the
    #: narration is not.
    hints: tuple[str, ...] = ()
    #: True when this line was read by field position (UPI, IMPS, ACH, bill pay...). The narration text of such a line carries
    #: the payer's note, VPAs and phone numbers the page layout may have split so that no masking can see them, and the channel,
    #: the payee token and the hints already say what a classifier needs. So the text itself is not sent to a model.
    withhold_text: bool = False

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


# ---------------------------------------------------------------------------
# Bank formats read by position. These are tried after the patterns above and before the catch-alls below, so a
# narration with "fee" or "GST" in a remark is read as the UPI or IMPS payment it is, not as a bank charge.
# ---------------------------------------------------------------------------

_IFSC_SHAPE = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}", re.I)
_BANK_WORDS = re.compile(
    r"\b(?:BANK|BK|KOTAK|HDFC|ICICI|AXIS|SBI|IDBI|CANARA|PNB|UCO|IOB|BOB|BOI|BOM|YES|INDUSIND|FEDERAL|RBL|UNION|KARUR|"
    r"PAYTM|PAYMENTS)\b",
    re.I,
)
#: A field that is the payer's note, not a name, when it opens a transfer.
_NOTE_FIELD = re.compile(r"^(?:TO|FROM|FAMILY|MYSELF|SELF|PAYOUT)\b", re.I)


def _is_ifsc(field: str) -> bool:
    """An IFSC, though the page layout may have put spaces inside it (``HDF C0000006``)."""
    return bool(_IFSC_SHAPE.fullmatch(re.sub(r"\s+", "", field or "")))


def _bankish(field: str) -> bool:
    return _is_ifsc(field) or bool(_BANK_WORDS.search(field or ""))


#: Words a bank prints in a payee's place: a direction, a mode, a scheme. Read as the payee they would become a rule key that
#: places every row of that kind.
_STRUCTURAL_WORDS = frozenset({
    "CR", "DR", "IN", "OUT", "REV", "P2P", "P2A", "P2M", "P2V", "UPI", "IMPS", "NEFT", "RTGS", "ACH", "NACH", "APBS",
    "MANDATE", "COLLECT", "PAY", "PAYMENT", "NA", "NIL", "NULL", "NONE", "SELF", "OTHERS", "OTHER", "TRANSFER",
})


def _name(field: str) -> str:
    """A name as printed, without the ellipsis a truncated one ends in. Empty when what is left cannot be a payee."""
    text = re.sub(r"\s+", " ", re.sub(r"[.\s]*\.\.\.\s*$", "", field or ""))
    # A long number after the name is a consumer, store or phone number, not part of who it is: it would leak, and it would make
    # the same payee a different key every month.
    text = re.sub(r"[\s.]*\d{4,}\W*$", "", text).strip(" /-.")
    if len(re.sub(r"[^A-Za-z]", "", text)) < 3 or text.upper() in _STRUCTURAL_WORDS:
        return ""
    return text


def _digits(field: str) -> str:
    return re.sub(r"\s+", "", field or "")


def _fields(rest: str) -> list[str]:
    return [f.strip() for f in rest.split("/") if f.strip() and not re.match(r"chg\s*rs", f.strip(), re.I)]


def _upi_by_position(raw: str):
    """UPI/<payee>/<vpa>/<note>/<bank>/<ref>/<id>, and the credit shapes that put the reference or a bare VPA first."""
    parts = raw.split("/")
    if len(parts) < 4 or parts[0].upper() != "UPI":
        return None
    first = parts[1].strip()
    if re.fullmatch(r"[\d\s]{9,}", first):
        return {"reference": _digits(first)}  # reference first: who the payee is varies by row, so none is read
    if "@" in first or not re.search(r"[A-Za-z]{2}", first):
        return {}
    return {"counterparty": _name(first)}


def _imps_by_position(raw: str):
    """MMT/IMPS/<ref>/<note>/<payee>/<IFSC>: the payee is the field just before the IFSC, and only then."""
    m = re.match(r"^MMT/IMPS/(?P<ref>[^/]*)/(?P<rest>.*)$", raw, re.I)
    if not m:
        return None
    fields = _fields(m.group("rest"))
    found = {"reference": _digits(m.group("ref"))}
    for i, field in enumerate(fields):
        if i >= 1 and _is_ifsc(field) and not _NOTE_FIELD.match(fields[i - 1]):
            found["counterparty"] = _name(fields[i - 1])
            break
    return found


def _bill_by_position(raw: str):
    m = re.match(r"^BIL/(?P<kind>BPAY|ONL|NEFT|IMPS)/(?P<ref>[^/]*)/(?P<rest>.*)$", raw, re.I)
    if not m:
        return None
    kind = m.group("kind").upper()
    fields = _fields(m.group("rest"))
    found = {"reference": _digits(m.group("ref"))}
    if kind in ("BPAY", "ONL"):
        biller = fields[1] if fields and fields[0].upper() == "BBPS" and len(fields) > 1 else (fields[0] if fields else "")
        if biller:
            found["counterparty"] = _name(biller)
        found["_channel"] = Channel.BILL
    else:
        found["_channel"] = Channel.NEFT if kind == "NEFT" else Channel.IMPS
        if len(fields) >= 2 and _bankish(fields[-1]) and not _NOTE_FIELD.match(fields[-2]):
            found["counterparty"] = _name(fields[-2])
    return found


def _internet_transfer(raw: str):
    """INF/NEFT/<utr>/<IFSC>/<payee> (to another bank) and INF/INFT/<utr>/<payee> (inside the bank)."""
    m = re.match(r"^INF/(?P<kind>NEFT|INFT|IMPS)/(?P<ref>[^/]*)/(?P<rest>.*)$", raw, re.I)
    if not m:
        return None
    kind = m.group("kind").upper()
    fields = _fields(m.group("rest"))
    found = {"reference": _digits(m.group("ref")), "_channel": Channel.TRANSFER if kind == "INFT" else Channel.NEFT}
    if kind == "INFT" and fields:
        found["counterparty"] = _name(fields[0])
    elif len(fields) >= 2 and _is_ifsc(fields[0]):
        found["counterparty"] = _name(fields[1])
    return found


def _card_merchant(raw: str):
    """VPS/<merchant>/<time>/<ref>/<city> and VIN/<merchant>/...: a debit-card purchase. A store number or WWW leads the name."""
    m = re.match(r"^(?:VPS|VIN)/(?P<merchant>[^/]*)/", raw, re.I)
    if not m:
        return None
    name = re.sub(r"^(?:\d+\s+|WWW\s+)", "", m.group("merchant").strip(), flags=re.I)
    return {"counterparty": _name(name)} if re.search(r"[A-Za-z]{3}", name) else {}


def _issuer(name: str) -> str:
    """The company behind a dividend credit: ``NTPC-FIN-DIV 24-25`` and ``NTPC-2ND INT-DIV 25-26`` are both NTPC."""
    if not re.search(r"DIV", name, re.I):
        return name
    stripped = re.sub(r"(?<=[A-Z])DIV(?:IDEND)?\d*$", "", name.strip(), flags=re.I)
    tokens = re.split(r"[-\s]+", stripped)
    keep = [
        t for t in tokens
        if t and not re.fullmatch(r"(?:FIN|FINAL|INT|INTERIM|DIV|DIVIDEND|DIV\d+|\d+(?:ST|ND|RD|TH)|\d{1,4})", t, re.I)
    ]
    return " ".join(keep) or name


def _dash_transfer(channel: str):
    pattern = re.compile(rf"^{channel}\s*-\s*(?P<reference>[A-Z0-9][A-Z0-9 ]*?)\s*-\s*(?P<counterparty>[^-]+?)\s*(?:-|$)", re.I)

    def read(raw: str):
        m = pattern.match(raw)
        return {"reference": _digits(m.group("reference")), "counterparty": _name(m.group("counterparty"))} if m else None

    return read


def _auto_debit_or_credit(raw: str):
    """ACH/<payer or biller>/<ref> and APBS/<scheme>/<ref>: a collection or credit under a standing mandate."""
    m = re.match(r"^(?:ACH|NACH|APBS)/(?P<name>[^/]*)(?:/(?P<ref>[^/]*))?", raw, re.I)
    if not m:
        return None
    found = {"counterparty": _issuer(_name(m.group("name")))}
    if m.group("ref"):
        found["reference"] = m.group("ref").strip()
    return found


_MORE_PATTERNS: list[tuple[str, object]] = [
    # 004401000001:Int.Pd:31-12-2025 to 29-03-2026 -- the bank's own interest, with the account number in front
    (Channel.INTEREST, re.compile(r"^(?:SB:)?(?P<account>\d{6,})\s*:\s*Int\.?\s*(?P<kind>Pd|Coll)", re.I)),
    (Channel.MANDATE, _auto_debit_or_credit),
    (Channel.UPI, _upi_by_position),
    (Channel.IMPS, _imps_by_position),
    (Channel.BILL, _bill_by_position),
    (Channel.TRANSFER, _internet_transfer),
    (Channel.POS, _card_merchant),
    # SBI: DEP TFR UPI/CR/<ref>/<payee>, WDL TFR UPI/DR/..., TO TRANSFER-UPI/DR/... (spaces are often missing)
    (
        Channel.UPI,
        re.compile(
            r"^(?:(?:DEP|WDL)\s*TFR|(?:TO|BY)\s*TRANSFER\s*-?)\s*UPI/(?P<kind>CR|DR)/(?P<reference>[^/]*)/(?P<counterparty>[^/]*)",
            re.I,
        ),
    ),
    # NEFT-HDFCH00000000001-DEMO CLEARING LIMITED-0001-0000000001- HDFC0000001 (reference first, payee second)
    *[(channel, _dash_transfer(channel)) for channel in (Channel.NEFT, Channel.RTGS)],
    # ICICI cash at an ATM: CAM/<machine>/CASH WDL, and its reversal CASH WDL RVSL
    (Channel.CASH, re.compile(r"^CAM/[^/]*/(?P<counterparty>CASH\s*(?:WDL|DEP)(?:\s*RVSL)?)", re.I)),
    (Channel.CASH, re.compile(r"^(?P<counterparty>CASH\s*DEPOSIT)", re.I)),
]

#: Rows read by position keep their text back from a model (see ``NarrationFacts.withhold_text``).
_POSITIONAL = frozenset(id(matcher) for _, matcher in _MORE_PATTERNS)

#: The leading word of a line no pattern read: enough to name the channel, never to name a payee. Never CASH: a seed rule posts
#: cash rows to Cash-in-Hand unseen, so cash is only ever claimed by a shape that has been seen.
_LEADING_CHANNEL = {
    "ACH": Channel.MANDATE, "NACH": Channel.MANDATE, "APBS": Channel.MANDATE,
    "UPI": Channel.UPI, "NEFT": Channel.NEFT, "RTGS": Channel.RTGS, "IMPS": Channel.IMPS, "MMT": Channel.IMPS,
    "POS": Channel.POS, "ECOM": Channel.POS, "VPS": Channel.POS, "VIN": Channel.POS,
    "BIL": Channel.BILL,
    "CHQ": Channel.CHEQUE, "CLG": Channel.CHEQUE,
}

#: Canonical purpose words, found by token. Each pattern stops at a letter on both sides, so DIV25 and INT-DIV hit while DIVYA
#: and INTERNET do not. What is reported is the name on the left, never the text that matched.
_HINTS: tuple[tuple[str, re.Pattern], ...] = tuple(
    (name, re.compile(pattern, re.I))
    for name, pattern in (
        ("DIVIDEND", r"(?<![A-Z])(?:DIVIDEND|DIV)(?![A-Z])|(?<=[A-Z]{4})DIV(?=\d|$)"),
        ("INTEREST", r"(?<![A-Z])INTEREST(?![A-Z])|(?<![A-Z])INT\.?\s?(?:PD|COLL)"),
        ("SUBSIDY", r"SUBSID"),
        ("REFUND", r"(?<![A-Z])REFUND"),
        ("REVERSAL", r"(?<![A-Z])(?:RVSL|REVERSAL|REVERSED)"),
        ("CHARGES_INCLUDED", r"CHG\s?RS\s?\d"),
        ("SALARY", r"(?<![A-Z])(?:SALARY|PAYROLL)(?![A-Z])"),
        ("RENT", r"(?<![A-Z])RENT(?![A-Z])"),
        ("LOAN_EMI", r"(?<![A-Z])(?:EMI|LOAN)(?![A-Z])"),
        ("INSURANCE", r"INSURA|(?<![A-Z])(?:LIC|PREMIUM)(?![A-Z])"),
        ("ELECTRICITY", r"ELECTRICITY|MSEDCL|BESCOM|MAHAVITARAN|TORRENT\s?POWER"),
        ("TELECOM", r"VODAFONE|AIRTEL|(?<![A-Z])(?:JIO|BSNL|VI)(?![A-Z])|POSTPAI|RECHARGE|BROADBAND"),
        ("DTH_TV", r"TATA\s?PLAY|DISH\s?TV|(?<![A-Z])DTH(?![A-Z])"),
        ("FUEL", r"(?<![A-Z])(?:PETROL|DIESEL|FUEL)(?![A-Z])"),
        ("SUBSCRIPTION", r"NETFLIX|HOTSTAR|SPOTIFY|YOUTUBE|PRIME\s?VIDEO|SUBSCRIPTION"),
        ("RECURRING", r"MANDAT|RECURRING|AUTOPAY"),
        ("SHOPPING", r"AMAZON|FLIPKART|MYNTRA|AJIO|NYKAA|MEESHO|SNAPDEAL|DMART|BIGBASKET|BLINKIT|ZEPTO"),
        ("FOOD", r"ZOMATO|SWIGGY|DINNER|LUNCH|BREAKFAST|RESTAURANT|RESTAU"),
        ("INVESTMENT", r"ZERODHA|GROWW|UPSTOX|ANGEL\s?ONE|GEOJIT|INDIAN\s?CLE|MUTUAL\s?FUND|(?<![A-Z])(?:SIP|IPO|NSDL|CDSL)(?![A-Z])"),
        ("EDUCATION", r"SCHOOL|COLLEGE|TUITION|UNIVERSITY|ACADEMY"),
        ("TRAVEL", r"IRCTC|REDBUS|MAKEMYTRIP|MSRTC|FASTAG|(?<![A-Z])(?:UBER|OLA)(?![A-Z])"),
        ("BILL_PAYMENT", r"BILLPAY|BBPS"),
    )
)


def _hints(raw: str) -> tuple[str, ...]:
    text = (raw or "").upper().replace("_", " ")
    return tuple(name for name, pattern in _HINTS if pattern.search(text))


#: What a bank's page layout glues onto the end of a narration when the PDF is read: not part of the transaction, and it
#: would otherwise make the same payee look different on every page.
_PAGE_FOOTER = re.compile(r"\s+(?:www\.[a-z0-9.-]+|legends\s+for\s+transactions\b).*$", re.I | re.S)


def _lead_channel(raw: str) -> str:
    m = re.match(r"[A-Za-z]+", raw)
    return _LEADING_CHANNEL.get(m.group(0).upper(), Channel.UNKNOWN) if m else Channel.UNKNOWN


def _read(matcher, raw: str):
    """What a pattern (a regex or a function) found in ``raw``, or None when it does not apply. An empty dict is a match."""
    if callable(matcher):
        return matcher(raw)
    match = matcher.match(raw)
    return {k: v for k, v in match.groupdict().items() if v} if match else None


_PATTERNS: list[tuple[str, object]] = [
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
    # --- Formats from other banks. The ones above came from one real statement; these are the
    # --- shapes the other large Indian banks print, so a payee is found whichever bank it is.
    # NEFT CR-HDFC0001234-ORBIT RETAIL PVT LTD-INV 1042   (also RTGS, IMPS; CR/DR optional)
    *[
        (
            channel,
            re.compile(
                rf"^{channel}\s*(?:CR|DR)?\s*-\s*(?P<counterparty_bank>[A-Z]{{4}}0[A-Z0-9]{{6}})\s*-\s*"
                r"(?P<counterparty>[^-]+?)\s*(?:-\s*(?P<remark>.*))?$",
                re.I,
            ),
        )
        for channel in (Channel.NEFT, Channel.RTGS, Channel.IMPS)
    ],
    # UPI/410123456789/Payment to BigBasket   ·   UPI/5012.../HOLDER NAME/Payment from ABC
    (
        Channel.UPI,
        re.compile(
            r"^UPI/(?P<reference>[^/]*)/(?:[^/]*/)*?(?:PAYMENT|PAID|PAY)\s+(?:TO|FROM)\s+(?P<counterparty>[^/]+?)\s*/?$",
            re.I,
        ),
    ),
    # UPI-SWIGGY-9876543210 · UPI-RAMESH KUMAR-ramesh@okicici-...
    (Channel.UPI, re.compile(r"^UPI-(?P<counterparty>[^-]+?)\s*-\s*(?P<reference>.*)$", re.I)),
    # ACH D- LIC OF INDIA · NACH DR-TATA CAPITAL-EMI · ACH C- DIVIDEND XYZ LTD
    (Channel.MANDATE, re.compile(r"^N?ACH\s*(?:D|C|DR|CR)?\s*-\s*(?P<counterparty>[^-]+?)\s*(?:-\s*(?P<remark>.*))?$", re.I)),
    # CHQ DEP-000412-CLEARING-MEHTA HARDWARE · CHQ DEP/000412/MEHTA HARDWARE
    (
        Channel.CHEQUE,
        re.compile(
            r"^CHQ\s*DEP[-/\s]+(?P<instrument>\d+)?[-/\s]*(?:CLEARING[-/\s]+|CLG[-/\s]+)?(?P<counterparty>.+)$",
            re.I,
        ),
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
    *_MORE_PATTERNS,
    (Channel.CASH, re.compile(r"^(?P<counterparty>CWDR|ATM-CASH|CASH\s+DEP)", re.I)),
    # A tax paid through the bank -- a GST challan (CPIN), income tax or TDS through CBDT/OLTAS --
    # is a payment against a liability, never a bank charge. It has to be recognised before
    # the FEE line below, which matches "GST" for the bank's own "GST on charges" rows and
    # would otherwise send a GST payment to Bank Charges, where a seed rule posts it unseen.
    (
        Channel.TAX,
        re.compile(
            r"^(?P<counterparty>.*(?:\bCPIN\b|GST\s*(?:PAYMENT|PMT|CHALLAN)|GSTN|CBDT|OLTAS|TAX\s*PAYMENT|TDS\s*PAYMENT|CHALLAN).*)$",
            re.I,
        ),
    ),
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
    raw = _PAGE_FOOTER.sub("", re.sub(r"\s+", " ", (narration or "").strip()))
    hints = _hints(raw)

    for channel, pattern in _PATTERNS:
        found = _read(pattern, raw)
        if found is None:
            continue
        groups = {k: _clean(v) for k, v in found.items() if v}
        channel = groups.pop("_channel", channel)
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
            hints=hints,
            withhold_text=id(pattern) in _POSITIONAL,
        )

    # Nothing read it. The leading word still says how the money moved; no payee is guessed.
    channel = _lead_channel(raw)
    return NarrationFacts(
        raw=raw,
        channel=channel,
        is_self_transfer=channel in _TRANSFERABLE and _looks_like_self(raw, "", account_holder, own_accounts),
        hints=hints,
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
    if any(marker in upper for marker in _SELF_MARKERS) or re.search(r"\bMYSELF\b", upper):
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
