"""What a model is allowed to see of a transaction.

Design principle one: the best way not to leak data to a third party is not to
send it. Before any row leaves for a model it is reduced to the shape a
classifier needs and nothing else. Concretely, per row:

* **The narration is masked** with :func:`core.masking.mask` -- account
  numbers, references, PAN, GSTIN, phones, cards, emails become typed
  placeholders. The same function masks every log line, so what the model can
  see and what the log can hold are one definition.
* **Known vendors become their alias token.** A client's vendor list is the
  firm's data; the model gets ``V3F9A1C2B0`` and the mapping back happens
  here, server-side. The model can still say "this is the same party as last
  time" without ever learning who that is.
* **People become provisional aliases.** A counterparty that looks like a
  person's name -- capitalised words, no business marker -- is replaced with a
  stable pseudonym. A business name is left in, because "GODAVARI RESTAURANT"
  is the single most useful word for placing the row and a company name is not
  personal data. This is a judgement, recorded here so it can be revisited: a
  firm that wants no counterparty names sent at all flips
  ``LLM_SHARE_BUSINESS_NAMES`` to false and every party becomes an alias.
* **The client's own name is never sent.** A transfer to the account holder is
  marked ``self`` and the name dropped.
* **Amounts become bands.** The model needs to know whether this is a coffee
  or a car; it does not need the paise.

What the model receives for a row is therefore: channel, direction, an amount
band, the masked narration with parties substituted, and the remark if the
bank carried one. What it gets back is a ledger *name* from the list it was
given, which is validated against that list before anything is written.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from django.conf import settings

from classify.narration import Channel, analyse, normalise
from core.masking import mask

#: Words that mark a counterparty as an organisation rather than a person.
_BUSINESS_MARKERS = re.compile(
    r"\b(LTD|LIMITED|PVT|PRIVATE|LLP|INC|CORP|CO|COMPANY|ENTERPRISES?|INDUSTRIES|"
    r"TRADERS?|TRADING|STORES?|MART|SUPERMARKET|SHOP|AGENC(?:Y|IES)|SERVICES?|SOLUTIONS?|"
    r"TECHNOLOG(?:Y|IES)|SYSTEMS?|SOFTWARE|LABS?|CLINIC|HOSPITAL|PHARMA(?:CY)?|MEDICAL|"
    r"RESTAURANT|RESTAU|HOTEL|CAFE|FOODS?|BAKERY|SWEETS|KITCHEN|"
    r"BANK|FINANCE|FINANCIAL|INSURANCE|ASSURANCE|SECURITIES|BROKING|CAPITAL|MUTUAL|FUND|"
    r"TELECOM|MOBILE|ELECTRIC(?:ITY|ALS?)?|POWER|GAS|WATER|MUNICIPAL|CORPORATION|NIGAM|"
    r"PETROL|PETROLEUM|FUELS?|MOTORS?|AUTO|TRAVELS?|TOURS?|LOGISTICS|TRANSPORT|COURIER|"
    r"SCHOOL|COLLEGE|UNIVERSITY|ACADEMY|INSTITUTE|TRUST|SOCIETY|ASSOCIATION|FOUNDATION|"
    r"GOVT|GOVERNMENT|DEPARTMENT|OFFICE|OFFICER|COMMISSION|BOARD|AUTHORITY|TAX|GST|"
    r"ZERODHA|GROWW|UPSTOX|PAYTM|PHONEPE|GOOGLEPAY|AMAZON|FLIPKART|SWIGGY|ZOMATO|OLA|UBER|"
    r"JIO|AIRTEL|VODAFONE|BSNL|IRCTC|MSEDCL|BESCOM|TATA|RELIANCE|BAJAJ|HDFC|ICICI|SBI|AXIS|"
    r"KOTAK|LIC|IPPF|PPF|SWEEP|INTEREST|CREDIT CARD|CASHBACK|REFUND|CHARGES?|FEE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModelRow:
    """One transaction as the model will see it."""

    key: str
    channel: str
    direction: str
    amount_band: str
    narration: str
    counterparty: str
    remark: str
    is_self_transfer: bool
    #: Placeholder -> count, from the masking pass. Recorded, not sent.
    removed: dict[str, int] = field(default_factory=dict)

    def as_prompt_dict(self) -> dict:
        return {
            "key": self.key,
            "channel": self.channel,
            "direction": self.direction,
            "amount_band": self.amount_band,
            "counterparty": self.counterparty,
            "remark": self.remark,
            "narration": self.narration,
            "self_transfer": self.is_self_transfer,
        }


def amount_band(paise: int) -> str:
    """Coarse magnitude. Enough to tell a stationery bill from a property deal."""
    rupees = abs(paise) / 100
    if rupees < 100:
        return "under ₹100"
    if rupees < 1_000:
        return "₹100–1,000"
    if rupees < 10_000:
        return "₹1,000–10,000"
    if rupees < 100_000:
        return "₹10,000–1 lakh"
    if rupees < 1_000_000:
        return "₹1–10 lakh"
    return "over ₹10 lakh"


def person_alias(name: str, firm_id) -> str:
    """A stable pseudonym for a person, unique within a firm, meaningless outside."""
    seed = f"{firm_id}|person|{normalise(name)}".encode()
    return "P" + hashlib.sha256(seed).hexdigest()[:8].upper()


def looks_like_a_person(counterparty: str) -> bool:
    """Capitalised words, no organisation marker. Errs towards 'person'.

    Erring that way is the safe direction: a business wrongly treated as a
    person costs the model a hint; a person wrongly treated as a business sends
    a name out of the building.
    """
    text = counterparty.strip()
    if not text:
        return False
    if _BUSINESS_MARKERS.search(text):
        return False
    words = re.findall(r"[A-Za-z]+", text)
    if not words:
        return False
    if len(words) > 4:
        return False
    if re.search(r"[@/_.\d]", text):
        return False
    return True


class Pseudonymiser:
    """Turns a client's transactions into rows a model may see.

    Built once per batch: it loads the client's vendor aliases and account
    holder once rather than per row.
    """

    def __init__(self, client, *, vendors, account_holder: str = "", own_accounts=()):
        self.client = client
        self.firm_id = client.firm_id
        self.account_holder = account_holder
        self.own_accounts = tuple(own_accounts)
        #: normalised canonical name -> alias token
        self._aliases = {normalise(v.canonical_name): v.alias_token for v in vendors}
        self._alias_to_vendor = {v.alias_token: v for v in vendors}
        self.share_business_names = bool(getattr(settings, "LLM_SHARE_BUSINESS_NAMES", True))

    # -- outwards --------------------------------------------------------------

    def row(self, transaction, key: str | None = None) -> ModelRow:
        facts = analyse(transaction.narration, self.account_holder, self.own_accounts)
        masked = mask(facts.raw)
        narration = masked.text

        party = ""
        if facts.is_self_transfer:
            party = "self"
            if facts.counterparty:
                narration = _replace(narration, facts.counterparty, "<SELF>")
        elif facts.counterparty:
            party = self.party_token(facts.counterparty)
            if party != facts.counterparty:
                narration = _replace(narration, facts.counterparty, party)

        direction = "debit" if transaction.is_debit else "credit"
        return ModelRow(
            key=key or str(transaction.pk),
            channel=facts.channel if facts.channel != Channel.UNKNOWN else "UNKNOWN",
            direction=direction,
            amount_band=amount_band(transaction.amount_paise),
            narration=narration,
            counterparty=party,
            remark=mask(facts.remark).text if facts.remark else "",
            is_self_transfer=facts.is_self_transfer,
            removed=masked.removed,
        )

    def party_token(self, counterparty: str) -> str:
        """The counterparty as the model sees it: alias, pseudonym, or name."""
        known = self._aliases.get(normalise(counterparty))
        if known:
            return known
        if looks_like_a_person(counterparty) or not self.share_business_names:
            return person_alias(counterparty, self.firm_id)
        return mask(counterparty).text

    # -- back ------------------------------------------------------------------

    def vendor_for_alias(self, alias: str):
        """Resolve a vendor alias the model handed back. None if it made one up."""
        return self._alias_to_vendor.get((alias or "").strip().upper())

    @property
    def known_aliases(self) -> list[str]:
        return sorted(self._alias_to_vendor)


def _replace(text: str, needle: str, replacement: str) -> str:
    """Replace ``needle`` in ``text`` ignoring case, spacing and punctuation drift.

    The counterparty was cut out of the narration by the analyser, so it is in
    there -- but the masking pass may have changed digits inside it, and banks
    wrap names mid-word. Matching on the normalised form catches all of that.
    """
    target = normalise(needle)
    if not target:
        return text
    # Walk the text, comparing a running normalised window against the target.
    letters = [(i, c.upper()) for i, c in enumerate(text) if c.isalnum()]
    norm = "".join(c for _, c in letters)
    start = norm.find(target)
    if start == -1:
        return text
    first = letters[start][0]
    last = letters[start + len(target) - 1][0]
    return text[:first] + replacement + text[last + 1 :]
