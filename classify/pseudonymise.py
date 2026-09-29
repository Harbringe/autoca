"""What a model is allowed to see of a transaction.

Design principle one: the best way not to leak data to a third party is not to
send it. Before any row leaves for a model it is reduced to the shape a
classifier needs and nothing else. Concretely, per row:

* **The narration is masked** with :func:`core.masking.mask` -- account
  numbers, references, PAN, GSTIN, phones, cards, emails become typed
  placeholders. The same function masks every log line, so what the model can
  see and what the log can hold are one definition.
* **Known parties become their alias token.** A client's party list is the
  firm's data; the model gets ``V3F9A1C2B0`` and the mapping back happens
  here, server-side. The model can still say "this is the same party as last
  time" without ever learning who that is.
* **People become provisional aliases.** A counterparty is a person's name
  unless it carries a business marker word, and is replaced -- every occurrence
  of it, in the narration and the remark -- with a stable pseudonym. UPI
  addresses are masked. When no counterparty can be found the free text is not
  sent at all. A business name is left in, because "GODAVARI RESTAURANT"
  is the single most useful word for placing the row and a company name is not
  personal data. This is a judgement, recorded here so it can be revisited: a
  firm that wants no counterparty names sent at all flips
  ``LLM_SHARE_BUSINESS_NAMES`` to false and every party becomes an alias.
* **The client's own name is never sent.** A transfer to the account holder is
  marked ``self`` and the name dropped.
* **Amounts and dates go out exactly.** They used to go out as bands; a
  bookkeeper cannot recognise a refund without seeing that it is the same
  amount as the payment three weeks earlier, and an amount is not personal
  data. The band function is kept for display.

What the model receives for a row is therefore: date, channel, direction, the
exact amount, the masked narration with parties substituted, and the remark
if the bank carried one. What it gets back is a ledger *name* from the list it was
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
    #: Rupees with paise, as text, e.g. "2450.00".
    amount: str
    #: dd-mm-yyyy, the way the statement prints it.
    date: str
    narration: str
    counterparty: str
    remark: str
    is_self_transfer: bool
    #: Placeholder -> count, from the masking pass. Recorded, not sent.
    removed: dict[str, int] = field(default_factory=dict)

    def as_prompt_dict(self) -> dict:
        return {
            "key": self.key,
            "date": self.date,
            "channel": self.channel,
            "direction": self.direction,
            "amount": self.amount,
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
    """Anything without an organisation marker. Errs towards 'person'.

    Erring that way is the safe direction: a business wrongly treated as a
    person costs the model a hint; a person wrongly treated as a business sends
    a name out of the building. Initials, long names and names with a digit or
    punctuation in them are people too.
    """
    text = counterparty.strip()
    if not text:
        return False
    return not _BUSINESS_MARKERS.search(text.replace("_", " "))


class Pseudonymiser:
    """Turns a client's transactions into rows a model may see.

    Built once per batch: it loads the client's party aliases and account
    holder once rather than per row.
    """

    def __init__(self, client, *, parties, account_holder: str = "", own_accounts=(), spellings=()):
        self.client = client
        self.firm_id = client.firm_id
        self.account_holder = account_holder
        self.own_accounts = tuple(own_accounts)
        #: normalised canonical name -> alias token
        self._aliases = {normalise(v.canonical_name): v.alias_token for v in parties}
        self._alias_to_party = {v.alias_token: v for v in parties}
        # ``spellings`` are ``PartyAlias`` rows: a spelling a person has confirmed
        # is the same party as its canonical name, so it gets the same token.
        # Without this a confirmed alias was remembered by the resolver and then
        # ignored here -- the model was sent the raw spelling of a party the firm
        # had already identified, and could not join it to that party's history.
        #
        # Passed in rather than read here so that building a Pseudonymiser stays
        # free of database access, as it always was.
        by_pk = {v.pk: v for v in parties}
        for alias in spellings:
            party = by_pk.get(alias.party_id)
            if party is not None:
                self._aliases.setdefault(alias.alias_normalised, party.alias_token)
        self.share_business_names = bool(getattr(settings, "LLM_SHARE_BUSINESS_NAMES", True))
        #: person token -> the name as the bank spelled it. Never sent; it lets
        #: what the model writes be turned back into words before it is stored.
        self._people: dict[str, str] = {}

    # -- outwards --------------------------------------------------------------

    def row(self, transaction, key: str | None = None) -> ModelRow:
        facts = analyse(transaction.narration, self.account_holder, self.own_accounts)
        masked = mask(facts.raw)
        narration = masked.text
        remark = mask(facts.remark).text if facts.remark else ""

        party = ""
        if not facts.counterparty:
            # Free text with no counterparty found is where a name hides that no
            # rule could locate. Channel, direction, amount and date still go.
            narration = remark = ""
            if facts.is_self_transfer:
                party = "self"
        elif facts.is_self_transfer:
            party = "self"
            narration = _replace(narration, facts.counterparty, "<SELF>", words=True)
            remark = _replace(remark, facts.counterparty, "<SELF>", words=True)
        else:
            party = self.party_token(facts.counterparty)
            if party != facts.counterparty:
                words = looks_like_a_person(facts.counterparty)
                narration = _replace(narration, facts.counterparty, party, words=words)
                remark = _replace(remark, facts.counterparty, party, words=words)

        direction = "debit" if transaction.is_debit else "credit"
        return ModelRow(
            key=key or str(transaction.pk),
            channel=facts.channel if facts.channel != Channel.UNKNOWN else "UNKNOWN",
            direction=direction,
            amount_band=amount_band(transaction.amount_paise),
            amount=f"{abs(transaction.amount_paise) / 100:.2f}",
            date=transaction.value_date.strftime("%d-%m-%Y"),
            narration=narration,
            counterparty=party,
            remark=remark,
            is_self_transfer=facts.is_self_transfer,
            removed=masked.removed,
        )

    def party_token(self, counterparty: str) -> str:
        """The counterparty as the model sees it: alias, pseudonym, or name."""
        known = self._aliases.get(normalise(counterparty))
        if known:
            return known
        if looks_like_a_person(counterparty) or not self.share_business_names:
            token = person_alias(counterparty, self.firm_id)
            self._people.setdefault(token, counterparty)
            return token
        return mask(counterparty).text

    # -- back ------------------------------------------------------------------

    def party_for_alias(self, alias: str):
        """Resolve a party alias the model handed back. None if it made one up."""
        return self._alias_to_party.get((alias or "").strip().upper())

    def name_for_token(self, token: str) -> str | None:
        """The name behind a token this batch sent: a known party's, or a person's.

        None for a token the model made up or carried over from elsewhere.
        """
        token = (token or "").strip().upper()
        party = self._alias_to_party.get(token)
        if party is not None:
            return party.canonical_name
        return self._people.get(token)

    @property
    def known_aliases(self) -> list[str]:
        return sorted(self._alias_to_party)

    @property
    def known_parties(self) -> list[dict]:
        """Each known party as ``{alias, name}`` -- the name only where it may go out.

        A business name is not personal data and is already sent in the clear
        whenever it appears in a narration, so listing the client's known
        businesses adds nothing the model could not see. A person's name never
        goes out, so a person appears here by alias alone -- which is exactly
        why the model cannot suggest a match for one by name, and why a person
        is only ever recognised by a fact or a confirmed spelling.
        """
        out = []
        for alias, party in sorted(self._alias_to_party.items()):
            entry = {"alias": alias}
            if self.share_business_names and not looks_like_a_person(party.canonical_name):
                entry["name"] = party.canonical_name
            out.append(entry)
        return out


def _replace(text: str, needle: str, replacement: str, *, words: bool = False) -> str:
    """Replace every occurrence of ``needle`` in ``text`` ignoring case, spacing and punctuation drift.

    The counterparty was cut out of the narration by the analyser, so it is in
    there -- but the masking pass may have changed digits inside it, and banks
    wrap names mid-word. Matching on the normalised form catches all of that.
    A name also turns up again in the payer's remark, so every span goes, not
    the first. With ``words``, each separate word of the name goes too: a payer
    who types only "Ramesh" has still named the person.
    """
    target = normalise(needle)
    if not target or not text:
        return text
    letters = [(i, c.upper()) for i, c in enumerate(text) if c.isalnum()]
    norm = "".join(c for _, c in letters)
    spans = []
    at = norm.find(target)
    while at != -1:
        spans.append((letters[at][0], letters[at + len(target) - 1][0]))
        at = norm.find(target, at + len(target))
    for first, last in reversed(spans):
        text = text[:first] + replacement + text[last + 1 :]
    if words:
        for word in {w for w in re.findall(r"[A-Za-z]{3,}", needle) if w.upper() not in _NOT_NAMES}:
            text = re.sub(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", replacement, text, flags=re.IGNORECASE)
    return text


#: Words a name can share with the structure of a narration; replacing them would only break it.
_NOT_NAMES = frozenset({"UPI", "NEFT", "IMPS", "RTGS", "CHQ", "MOB", "TRF", "ACH", "NACH", "PAY", "PAID", "TO", "FROM"})
