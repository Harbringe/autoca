"""Which counterparties in a client's statements look like real suppliers or customers, for a person to confirm.

Nothing is created here. A bank statement names everyone the client ever paid or was paid by, and most of them are not
parties in the accounting sense: the client's own accounts, bank charges, tax, cash, one-off payees. Turning every one into a
ledger would bury the chart. So this only *proposes*: it groups the rows that have no party yet by who they were with, leaves
out what is plainly not a party, ranks the rest by how often and how much, and suggests a role from the direction of the
money (paid out: a supplier, received: a customer, both: both). A person ticks the real ones; ``create_parties`` then makes
them and links every row of theirs that is still waiting, and later statements recognise them by the usual resolution.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from django.db.models import Q

from classify.engine import party_for
from classify.models import Party, PartyRole, TransactionClassification
from classify.narration import Channel, normalise
from classify.parties import WEAK, confirm_alias
from classify.parties import _similarity_key as parties_key

#: A payee seen once is probably a one-off. A person can still create it from the full list.
MIN_APPEARANCES = 2

#: Channels that are the bank or the state, not a trading counterparty.
NOT_A_PARTY_CHANNELS = frozenset({Channel.INTEREST, Channel.SWEEP, Channel.TAX, Channel.FEE, Channel.CASH})


@dataclass
class Candidate:
    name: str
    key: str
    count: int = 0
    paid_paise: int = 0
    received_paise: int = 0
    first: object = None
    last: object = None
    rows: list = field(default_factory=list)

    @property
    def role(self) -> str:
        if self.paid_paise and self.received_paise:
            return PartyRole.BOTH
        return PartyRole.VENDOR if self.paid_paise else PartyRole.CUSTOMER


def candidates(client, *, min_appearances: int = MIN_APPEARANCES, include_one_offs: bool = False) -> list[Candidate]:
    """Counterparties with no party yet, most significant first."""
    rows = (
        TransactionClassification.objects.filter(
            firm_id=client.firm_id, transaction__bank_account__client=client, party__isnull=True, is_self_transfer=False
        )
        .exclude(counterparty="")
        .exclude(channel__in=NOT_A_PARTY_CHANNELS)
        .select_related("transaction")
    )
    known = {normalise(p.canonical_name) for p in Party.objects.filter(firm_id=client.firm_id, client=client)}
    found: dict[str, Candidate] = {}
    for row in rows:
        key = normalise(row.counterparty)
        if not key or key in known:
            continue
        item = found.setdefault(key, Candidate(name=" ".join(row.counterparty.split()), key=key))
        txn = row.transaction
        item.count += 1
        if txn.is_debit:
            item.paid_paise += txn.amount_paise
        else:
            item.received_paise += txn.amount_paise
        item.first = txn.value_date if item.first is None else min(item.first, txn.value_date)
        item.last = txn.value_date if item.last is None else max(item.last, txn.value_date)
        item.rows.append(row.pk)
    threshold = 1 if include_one_offs else min_appearances
    chosen = [c for c in found.values() if c.count >= threshold]
    return sorted(chosen, key=lambda c: (-c.count, -(c.paid_paise + c.received_paise), c.name))


def create_parties(client, wanted: list[dict]) -> list[Party]:
    """Make the parties a person ticked, and attach every waiting row of theirs.

    ``wanted`` is ``[{"name": ..., "role": ...}]``. A party that already exists (the same name, however the bank spaced it)
    is reused, so ticking twice, or two spellings of one payee, makes one party. Rows already posted are linked too: the
    party is only a label on the classification, so linking changes no entry. Moving a posted payment onto the party's
    account is a separate decision (see settlement).
    """
    made: list[Party] = []
    by_key = {c.key: c for c in candidates(client, include_one_offs=True)}
    for item in wanted:
        name = " ".join(str(item.get("name", "")).split())
        if not name:
            continue
        role = item.get("role") or PartyRole.VENDOR
        if role not in PartyRole.values:
            role = PartyRole.VENDOR
        party = party_for(client, name)
        if party.role != role and not party.bills.exists():
            party.role = role
            party.save(update_fields=["role"])
        made.append(party)
        match = by_key.get(item.get("key") or normalise(name))
        if match:
            TransactionClassification.objects.filter(
                Q(pk__in=match.rows), firm_id=client.firm_id, party__isnull=True
            ).update(party=party, party_resolution="CONFIRMED")
    return made


# ---------------------------------------------------------------------------
# Opening the obvious ones without being asked
# ---------------------------------------------------------------------------

#: Words that say a payee is a business, so even a short name ("Om Traders") is one.
_BUSINESS_WORDS = frozenset(
    {"TRADERS", "TRADING", "TEXTILES", "TEXTILE", "ENTERPRISES", "ENTERPRISE", "AGENCIES", "AGENCY", "STORES", "STORE", "MILLS", "MILL",
     "FABRICS", "CREATION", "CREATIONS", "SAREES", "INDUSTRIES", "SYNTHETICS", "EXPORTS", "IMPEX", "COMPANY", "CO", "LTD", "LIMITED",
     "PVT", "LLP", "HUF", "EXPORT", "BROTHERS", "BROS", "SONS", "MARKETING", "SALES", "SUPPLIERS", "DISTRIBUTORS", "FASHION", "DESIGNER", "HANDLOOM",
     "SAREE", "SILK", "SILKS", "PRINTS", "PRINT", "FABRIC", "FABTEX", "SYNTEX", "GARMENTS", "DRESSES", "HOSIERY", "APPAREL", "APPARELS",
     "COLLECTION", "TEX", "CLOTH", "LOGISTICS", "TRANSPORT", "FASHIONS", "DESIGNERS", "HANDLOOMS"}
)

#: Narration words that mean the "name" is a payment channel or a bank's own word, not someone.
_NOT_A_NAME = frozenset({"UPI", "NEFT", "RTGS", "IMPS", "CASH", "CHARGES", "CHARGE", "INTEREST", "SMS", "ATM", "BANK", "SELF", "CHEQUE", "CHQ", "TRANSFER", "BY", "TO", "FROM"})


def _plain_words(name: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", name)


def looks_like_a_party(name: str) -> bool:
    """A name that is plainly a person or a business: letters, two words or more (or a business word), no handle, number or channel word.

    ``Kuldeep Textiles`` and ``Sainath Kashinath Bachewar`` pass; ``ASHOK``, ``8999938089@ybl``, ``BY CASH`` and ``Charges for PORD`` do not.
    The bar is deliberately high. A name that fails is still offered to a person in the found-parties list.
    """
    clean = " ".join(name.split())
    if not clean or any(ch.isdigit() for ch in clean) or "@" in clean or "/" in clean or ":" in clean:
        return False
    words = [w.upper() for w in _plain_words(clean)]
    if not words or any(w in _NOT_A_NAME for w in words):
        return False
    # Initials ("R S Designer", "J J Export") are fine when the name says what the business trades.
    if len(words) >= 2 and (all(len(w) >= 2 for w in words) or any(w in _TRADE_WORDS for w in words)):
        return True
    return len(words) == 1 and words[0] in _BUSINESS_WORDS


#: Payment collectors. Money from many customers reaches the bank through them, so none is a customer of its own: the
#: rows stay with the rest of the receipts (sales, or whatever the books say), never on an account named after the collector.
_COLLECTORS = (
    "GOOGLE INDIA DIGITAL", "GOOGLE PAY", "PAYTM", "PHONEPE", "RAZORPAY", "BHARATPE", "CASHFREE", "PAYU", "PINE LABS", "BILLDESK",
    "CCAVENUE", "AMAZON PAY", "MSWIPE", "EASEBUZZ", "INSTAMOJO",
)

#: "M/s", "M S" or "MS" in front of a business name is a courtesy, not part of the name.
_COURTESY = re.compile(r"^\s*M\s*/?\s*S\b\.?\s*", re.I)


def is_collector(name: str) -> bool:
    plain = " ".join(_plain_words(name)).upper()
    return any(word in plain for word in _COLLECTORS)


def _has_business_word(name: str) -> bool:
    return any(w.upper() in _BUSINESS_WORDS for w in _plain_words(name))


#: Business words that say *what* a business trades, unlike Ltd, Co or Pvt, which a power board or an insurer carries as well.
_TRADE_WORDS = _BUSINESS_WORDS - {"CO", "LTD", "LIMITED", "PVT", "LLP", "COMPANY", "HUF"}


def _distinct_key(name: str) -> str:
    """The part of a name that tells one business from another: "Arasana Silk Mills" is ARASANA, not SILK MILLS.

    Two textile mills share their trade words, so comparing whole names calls every pair alike and the second never gets an
    account. A name made only of trade words keeps them all.
    """
    words = [w for w in re.findall(r"[A-Z0-9]+", _COURTESY.sub("", name or "").upper()) if w not in _BUSINESS_WORDS]
    return "".join(sorted(words)) or parties_key(name)


def _trades(name: str) -> bool:
    return any(w.upper() in _TRADE_WORDS for w in _plain_words(name))


def tidy_name(name: str) -> str:
    """The name as a ledger should carry it: no "M/s" in front, and a bank's capitals turned into ordinary case.

    ``M S SHREE GANPATI SALES`` becomes ``Shree Ganpati Sales``. Short words (initials such as AV, or a final CO) keep their
    capitals. A name that already has small letters is left as it was written.
    """
    clean = " ".join(_COURTESY.sub("", name).split()) or " ".join(name.split())
    if clean != clean.upper():
        return clean
    return " ".join(w if len(w) <= 2 else w.capitalize() for w in clean.split(" "))


#: Words that mean the same thing in a name, written one way in a bank and another in a ledger.
_SAME_WORD = {"SHREE": "SHRI", "SRI": "SHRI", "SHREEJI": "SHRIJI"}

#: Company-ending words, which a bank often cuts short ("PVT L", "PRIVATE LT") or mistypes ("PEIVATE").
_ENDINGS = ("PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "CO", "COMPANY")


def _is_ending_fragment(word: str) -> bool:
    """A trailing scrap of a company ending: a cut-off ("L", "LT", "PV") or a slip ("PEIVATE" for PRIVATE)."""
    if len(word) <= 3 and any(e.startswith(word) for e in _ENDINGS):
        return True
    return len(word) >= 5 and any(difflib.SequenceMatcher(None, word, e).ratio() >= 0.7 for e in ("PRIVATE", "LIMITED"))


def _name_words(name: str) -> list[str]:
    from classify.parties import _ENTITY_WORDS

    words = [w for w in re.findall(r"[A-Z0-9]+", _COURTESY.sub("", name or "").upper()) if w not in _ENTITY_WORDS]
    return [_SAME_WORD.get(w, w) for w in words]


def _same_word(a: str, b: str) -> bool:
    """One word of a bank's spelling against one of a ledger's: the same, or one plural or one-letter slip apart.

    Short words (initials, "SAI") must match exactly: a slip in a six-letter name is a typo, in a three-letter one it is another name.
    """
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    stem = lambda w: w[:-1] if w.endswith("S") and len(w) > 4 else w  # noqa: E731  (MILLS / MILL, SYNTHETICS / SYNTHETIC)
    if stem(a) == stem(b):
        return True
    return len(a) >= 5 and len(b) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def reads_as(bank_name: str, ledger_name: str) -> bool:
    """True when a bank's spelling of a payee is the start of a ledger's name: Tally names carry a town, banks cut names short.

    ``NOVELTY TRADERS`` reads as ``Novelty Traders Gujarat``, ``NEEHA SILKS`` as ``M/s Neeha Silks ,AndhraPradesh``,
    ``PRATHAMESH COTTON MILL PVT L`` (cut off by the bank) as ``Prathamesh Cotton Mill Pvt Ltd,Kolhapur``, ``BHAWANI SILK MILLS``
    as ``Bhawani Silk Mill, Gujarat`` and ``PRAKESH CAP DEPOT PRIVATE LT`` as ``Prakash Cap Depot Pvt Ltd``. Every word of the
    bank's name must be the ledger's next word in order (a plural or a one-letter slip in a long word is the same word), the last
    one allowed to be cut short; two words at least, so a bare first name never matches. A resemblance, not a fact: it only ever
    proposes, and a person confirms.
    """
    bank, ledger = _name_words(bank_name), _name_words(ledger_name)
    # A bank cuts a name off mid-word, or mistypes the ending: what is left of a company ending is not a word of the name.
    while len(bank) >= 3 and (len(bank[-1]) == 1 or _is_ending_fragment(bank[-1])):
        bank = bank[:-1]
    if len(bank) < 2 or len(bank) > len(ledger):
        return False
    if not all(_same_word(b, w) for b, w in zip(bank[:-1], ledger, strict=False)):
        return False
    last, there = bank[-1], ledger[len(bank) - 1]
    return there.startswith(last) or _same_word(last, there)


def ledger_read_as(bank_name: str, ledgers):
    """The one ledger in ``ledgers`` that ``bank_name`` reads as, or None when none does or more than one could."""
    hits = [ledger for ledger in ledgers if reads_as(bank_name, ledger.name)]
    return hits[0] if len(hits) == 1 else None


@dataclass
class AutoOpened:
    party: Party
    ledger: object
    reason: str


def auto_open_parties(client, *, min_appearances: int = MIN_APPEARANCES) -> list[AutoOpened]:
    """Open a party, and its own account under Sundry Creditors or Sundry Debtors, for each payee that is clearly someone.

    A person or business that the statements name at least twice, whose name looks like one, and that resembles no party or ledger the client
    already has. A name that resembles one that exists is left alone: the party matcher offers it to a person, and merging two histories on
    a guess is the failure that module exists to prevent. Money paid out makes a supplier (Sundry Creditors), money received a customer
    (Sundry Debtors); a payee both ways takes the side with more money. The party's rows are linked, no posted entry changes.
    """
    from classify.models import LedgerAccount, LedgerGroup
    from ledger import billing

    ledgers = list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).values_list("name", "group"))
    existing_keys = [_distinct_key(n) for n in Party.objects.filter(firm_id=client.firm_id, client=client).values_list("canonical_name", flat=True)]
    existing_keys += [_distinct_key(n) for n, _g in ledgers]
    exact = {normalise(n): (n, g) for n, g in ledgers}
    # The account holder is the client's own owner: their deposits are capital and their withdrawals drawings, never a supplier or customer.
    holders = [parties_key(a.account_holder) for a in client.bank_accounts.all() if a.account_holder]

    # The client's own supplier and customer accounts (from Tally, or opened before): a bank spelling that reads as one of them is
    # that account's, and is proposed on it by ``place_on_party_accounts`` rather than given a second account of its own.
    party_ledgers = list(
        LedgerAccount.objects.filter(firm_id=client.firm_id, client=client, group__in=(LedgerGroup.CREDITOR, LedgerGroup.DEBTOR))
    )

    opened: list[AutoOpened] = []
    for candidate in candidates(client, min_appearances=1):
        # A business is a supplier or customer the first time it is paid; a person needs to be seen twice.
        if candidate.count < min_appearances and not _has_business_word(candidate.name):
            continue
        if not looks_like_a_party(candidate.name) or is_collector(candidate.name):
            continue
        if ledger_read_as(candidate.name, party_ledgers) is not None:
            continue
        if any(difflib.SequenceMatcher(None, parties_key(candidate.name), h).ratio() >= WEAK for h in holders):
            continue
        name, side = candidate.name, None
        if candidate.paid_paise or candidate.received_paise:
            side = LedgerGroup.DEBTOR if candidate.received_paise > candidate.paid_paise else LedgerGroup.CREDITOR
        taken = exact.get(candidate.key)
        if taken is not None:
            if taken[1] not in (LedgerGroup.CREDITOR, LedgerGroup.DEBTOR):
                continue  # the same name is already some other kind of ledger (an expense, a loan): not ours to turn into a party
            name, side = taken[0], taken[1]  # the ledger the client already has, spelled as it has it
        else:
            mine = _distinct_key(name)
            if any(difflib.SequenceMatcher(None, mine, other).ratio() >= WEAK for other in existing_keys):
                continue
        role = PartyRole.CUSTOMER if side == LedgerGroup.DEBTOR else PartyRole.VENDOR
        if taken is None:
            name = tidy_name(name)
        party = create_parties(client, [{"name": name, "role": role, "key": candidate.key}])[0]
        if normalise(party.canonical_name) != candidate.key:
            # The account is named tidily ("Shree Ganpati Sales"), so the bank's own spelling is remembered for it: next
            # month's statement then finds the party by fact, not by resemblance.
            confirm_alias(client, party, candidate.name)
        ledger = billing.party_ledger_for(party, side=side)
        times = "once" if candidate.count == 1 else f"{candidate.count} times"
        opened.append(
            AutoOpened(party, ledger, f"Named {times} in the statements; {'received from' if side == LedgerGroup.DEBTOR else 'paid to'}")
        )
        existing_keys.append(_distinct_key(name))
        party_ledgers.append(ledger)
    return opened


# ---------------------------------------------------------------------------
# Placing a party's money on its own account
# ---------------------------------------------------------------------------

#: A row whose party is known for a fact (its spelling, its account number) may be approved with the rest of the sure ones; one
#: on an account the bank's spelling only *reads as* is a proposal worth a look.
SURE_CONFIDENCE = 0.92
READ_AS_CONFIDENCE = 0.8

#: The trade heads a supplier's payment or a customer's receipt was booked to before parties had accounts of their own. A rule
#: that sends a known party's money there was learned from that habit, so the party's own account takes precedence over it.
_TRADE_GROUPS = ("PURCHASE", "SALES", "DIRECT_EXPENSE", "DIRECT_INCOME")


def place_on_party_accounts(client, *, only=None) -> set:
    """Propose every unposted row of a known supplier or customer on that party's own account. Returns the ids of the rows moved.

    ``only`` limits it to those classification ids (the batch the model has just read).

    This is how a Payment voucher reads in Tally: Dr the supplier, Cr the bank; a Receipt, Dr the bank, Cr the customer. The
    purchase or sale itself comes from the bill, never from the bank line. Only rows nobody decided, booked to a trade head
    (Purchases, Sales, direct expenses or incomes) by the model or a rule, or left unplaced with one as the model's idea, are moved: a person's choice stands, and so does an
    expense the model read as one. Run after each of the model's batches and after an upload. The row is a proposal: approving it
    posts it on account until the party's bills are matched to it (see ``ledger.approval``).
    """
    from classify.engine import not_decided_by_a_person
    from classify.models import ClassificationMethod, LedgerAccount, LedgerGroup
    from classify.treatment import band_for
    from ledger.openings import adopt_imported_party_ledgers

    adopt_imported_party_ledgers(client)
    accounts = list(
        LedgerAccount.objects.filter(
            firm_id=client.firm_id, client=client, group__in=(LedgerGroup.CREDITOR, LedgerGroup.DEBTOR), party_record__isnull=False
        ).select_related("party_record")
    )
    by_id = {ledger.pk: ledger for ledger in accounts}
    own = {a.ledger_name for a in client.bank_accounts.all()}
    rows = (
        not_decided_by_a_person(client)
        .filter(is_self_transfer=False)
        .exclude(counterparty="")
        .exclude(channel__in=NOT_A_PARTY_CHANNELS)
        .select_related("ledger", "party", "transaction")
    )
    if only is not None:
        rows = rows.filter(pk__in=list(only))
    placed = []
    for row in rows:
        # Only money booked to a trade head moves. The model (or a rule) has read what the payment was for: a supplier's goods
        # land in Purchases and go to the supplier's account, while an electricity bill or a premium stays an expense, since with
        # no bill behind it the expense would otherwise never reach the books.
        if is_collector(row.counterparty):
            continue
        sure = bool(row.party_id and row.party_resolution in ("AUTO", "CONFIRMED") and row.party.ledger_id in by_id)
        if row.ledger is not None:
            if row.ledger.group not in _TRADE_GROUPS:
                continue
        # Left unplaced: moved when the model's idea was a trade head, or when the payee is plainly a trading business (a mill, a
        # saree house), whatever the model guessed without seeing the party's account. A board or a person is left for it.
        elif row.suggested_ledger_group not in _TRADE_GROUPS and not _trades(row.counterparty):
            continue
        ledger = by_id[row.party.ledger_id] if sure else ledger_read_as(row.counterparty, accounts)
        if ledger is None or ledger.name in own or row.ledger_id == ledger.pk:
            continue
        party = ledger.party_record
        paid = row.transaction.is_debit
        row.ledger = ledger
        row.party = party
        row.method = ClassificationMethod.RULE
        row.rule = None
        row.confidence = SURE_CONFIDENCE if sure else READ_AS_CONFIDENCE
        row.review_band = band_for(row.confidence)
        row.needs_review = True
        row.model_state = None
        row.suggested_ledger_name = row.suggested_ledger_group = ""
        row.book_narration = ""
        if sure:
            row.rationale = (
                f"{'Paid to' if paid else 'Received from'} {party.canonical_name}: on their own account, as a Tally "
                f"{'Payment' if paid else 'Receipt'} voucher books it. The {'purchase' if paid else 'sale'} itself comes from the bill."
            )
        else:
            row.rationale = (
                f"The bank's {row.counterparty!r} reads as your ledger {ledger.name!r}. Check it is the same "
                f"{'supplier' if paid else 'customer'} before approving."
            )
        placed.append(row)
    TransactionClassification.objects.bulk_update(
        placed,
        [
            "ledger", "party", "method", "rule", "confidence", "review_band", "needs_review", "model_state",
            "suggested_ledger_name", "suggested_ledger_group", "book_narration", "rationale",
        ],
        batch_size=500,
    )
    return {row.pk for row in placed}
