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
from classify.parties import WEAK
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
        match = by_key.get(normalise(name))
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
     "PVT", "LLP", "HUF", "BROTHERS", "BROS", "SONS", "MARKETING", "SALES", "SUPPLIERS", "DISTRIBUTORS", "FASHION", "DESIGNER", "HANDLOOM"}
)

#: Narration words that mean the "name" is a payment channel or a bank's own word, not someone.
_NOT_A_NAME = frozenset({"UPI", "NEFT", "RTGS", "IMPS", "CASH", "CHARGES", "CHARGE", "SMS", "ATM", "BANK", "SELF", "CHEQUE", "CHQ", "TRANSFER", "BY", "TO", "FROM"})


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
    if len(words) >= 2 and all(len(w) >= 2 for w in words):
        return True
    return len(words) == 1 and words[0] in _BUSINESS_WORDS


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
    existing_keys = [parties_key(n) for n in Party.objects.filter(firm_id=client.firm_id, client=client).values_list("canonical_name", flat=True)]
    existing_keys += [parties_key(n) for n, _g in ledgers]
    exact = {normalise(n): (n, g) for n, g in ledgers}
    # The account holder is the client's own owner: their deposits are capital and their withdrawals drawings, never a supplier or customer.
    holders = [parties_key(a.account_holder) for a in client.bank_accounts.all() if a.account_holder]

    opened: list[AutoOpened] = []
    for candidate in candidates(client, min_appearances=min_appearances):
        if not looks_like_a_party(candidate.name):
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
            mine = parties_key(name)
            if any(difflib.SequenceMatcher(None, mine, other).ratio() >= WEAK for other in existing_keys):
                continue
        role = PartyRole.CUSTOMER if side == LedgerGroup.DEBTOR else PartyRole.VENDOR
        party = create_parties(client, [{"name": name, "role": role}])[0]
        ledger = billing.party_ledger_for(party, side=side)
        opened.append(
            AutoOpened(party, ledger, f"Named {candidate.count} times in the statements; {'received from' if side == LedgerGroup.DEBTOR else 'paid to'}")
        )
        existing_keys.append(parties_key(name))
    return opened
