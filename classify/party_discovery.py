"""Which counterparties in a client's statements look like real suppliers or customers, for a person to confirm.

Nothing is created here. A bank statement names everyone the client ever paid or was paid by, and most of them are not
parties in the accounting sense: the client's own accounts, bank charges, tax, cash, one-off payees. Turning every one into a
ledger would bury the chart. So this only *proposes*: it groups the rows that have no party yet by who they were with, leaves
out what is plainly not a party, ranks the rest by how often and how much, and suggests a role from the direction of the
money (paid out: a supplier, received: a customer, both: both). A person ticks the real ones; ``create_parties`` then makes
them and links every row of theirs that is still waiting, and later statements recognise them by the usual resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q

from classify.engine import party_for
from classify.models import Party, PartyRole, TransactionClassification
from classify.narration import Channel, normalise

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
