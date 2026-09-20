"""Ledgers a model creates, and a CA's decision about each.

The model may say "none of these ledgers fit; this client needs a Rent ledger".
It then gets one, ACTIVE at once, and the row is booked into it. Who created a
ledger does not matter to the books; what matters is that the entry is in the
right one, and a ledger that waits for a CA before it can hold anything just
turns every new head into a blocked row. The CA still sees every ledger the
model added (``proposal_reason`` is set only on those), and can rename it to
match the client's Tally spelling or merge it away -- ``accept`` and ``merge``
remain for that, and for anything still PROPOSED from before this change.

Three guards keep new ledgers from turning into a sprawl of near-duplicates:

* a proposal whose name is close to an existing ledger *is* that ledger;
* a proposal close to one a CA already rejected is dropped;
* a name matching the standard list takes the standard spelling.
"""

from __future__ import annotations

import difflib
import re

from django.db import transaction as db_transaction

from classify.models import ClassificationMethod, LedgerAccount, LedgerStatus
from classify.standard_ledgers import PROPOSABLE_GROUPS, STANDARD_LEDGERS
from classify.treatment import band_for

#: Two names at least this similar (after normalising) are treated as one.
SIMILARITY = 0.86

_NOISE = re.compile(r"\b(a/?c|account|ledger|exp|expenses?|charges?|paid)\b")

#: A pseudonym or party alias as the model sees them (``classify.pseudonymise``).
#: A ledger named after one would be a ledger named after a person -- the one
#: kind the model is told never to open, and the one kind that, if it slipped
#: through, would carry a pseudonym into the client's Tally.
_ALIAS_TOKEN = re.compile(r"\b[PV][0-9A-F]{8,}\b")


class ProposalError(ValueError):
    """The requested decision does not apply to this ledger."""


def name_key(name: str) -> str:
    lowered = _NOISE.sub(" ", name.lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]", "", lowered)


def clean_name(name: str) -> str:
    return " ".join(str(name or "").split())[:60]


def closest(name: str, ledgers) -> LedgerAccount | None:
    key = name_key(name)
    if not key:
        return None
    best, best_ratio = None, 0.0
    for ledger in ledgers:
        other = name_key(ledger.name)
        if not other:
            continue
        ratio = 1.0 if other == key else difflib.SequenceMatcher(None, key, other).ratio()
        if ratio > best_ratio:
            best, best_ratio = ledger, ratio
    return best if best_ratio >= SIMILARITY else None


def resolve_proposal(
    client, name, group, reason, *, known, excluded_names=(), allow_new: bool = True
) -> LedgerAccount | None:
    """Turn a model's proposed ledger into a ledger row, or refuse it.

    ``known`` is every ledger the client has in any status. Returns an existing
    ACTIVE or PROPOSED ledger when the proposal duplicates one, a new PROPOSED
    ledger when it is genuinely new, and None when it is invalid, duplicates a
    rejected proposal, or duplicates a name the caller excluded (the bank
    account the row came from).
    """
    name = clean_name(name)
    group = str(group or "")
    if len(name) < 3 or group not in PROPOSABLE_GROUPS or _ALIAS_TOKEN.search(name):
        return None

    match = closest(name, known)
    if match is not None:
        if match.status == LedgerStatus.REJECTED or match.name in excluded_names:
            return None
        return match
    if not allow_new:
        return None

    for standard_name, standard_group in STANDARD_LEDGERS:
        if name_key(standard_name) == name_key(name):
            name, group = standard_name, standard_group
            break

    ledger, _ = LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id,
        client=client,
        name=name,
        defaults={
            "group": group,
            "status": LedgerStatus.ACTIVE,
            "proposal_reason": str(reason or "")[:500],
        },
    )
    known.append(ledger)
    return None if ledger.status == LedgerStatus.REJECTED else ledger


@db_transaction.atomic
def accept(ledger: LedgerAccount, *, name: str | None = None, group: str | None = None) -> LedgerAccount:
    """A CA agrees the client needs this ledger, optionally fixing its name to match Tally."""
    _require_proposed(ledger)
    if name is not None:
        name = clean_name(name)
        if len(name) < 2:
            raise ProposalError("A ledger name is required.")
        clash = LedgerAccount.objects.filter(
            firm_id=ledger.firm_id, client_id=ledger.client_id, name=name
        ).exclude(pk=ledger.pk).first()
        if clash is not None:
            raise ProposalError(
                f"The client already has a ledger named {name!r}. Merge the proposal into it instead."
            )
        ledger.name = name
    if group is not None:
        ledger.group = group
    ledger.status = LedgerStatus.ACTIVE
    ledger.is_active = True
    ledger.save(update_fields=["name", "group", "status", "is_active"])
    return ledger


@db_transaction.atomic
def merge(ledger: LedgerAccount, into: LedgerAccount) -> int:
    """The client already has the right ledger; move this one's rows to it.

    Works on a live ledger too, as long as nothing has been posted to it: a
    ledger the model created this morning under a spelling the client's Tally
    does not use is exactly the case.
    """
    from ledger.models import JournalLine

    if JournalLine.objects.filter(ledger_account=ledger).exists():
        raise ProposalError(f"{ledger.name!r} already has posted entries; rename it instead of merging.")
    if into.pk == ledger.pk or into.client_id != ledger.client_id or into.status != LedgerStatus.ACTIVE:
        raise ProposalError("Merge into one of this client's ledgers that is already in use.")
    moved = ledger.classifications.update(ledger=into)
    ledger.delete()
    return moved


@db_transaction.atomic
def reject(ledger: LedgerAccount) -> int:
    """The client does not need this ledger. Its rows go back to the queue for a person."""
    _require_proposed(ledger)
    released = 0
    for row in ledger.classifications.all():
        row.ledger = None
        row.party = None
        row.rcm = False
        row.tds_section = ""
        row.method = ClassificationMethod.UNRESOLVED
        row.confidence = 0.0
        row.review_band = band_for(0.0)
        row.needs_review = True
        row.save(
            update_fields=[
                "ledger", "party", "rcm", "tds_section", "method", "confidence", "review_band", "needs_review",
            ]
        )
        released += 1
    ledger.status = LedgerStatus.REJECTED
    ledger.is_active = False
    ledger.save(update_fields=["status", "is_active"])
    return released


def _require_proposed(ledger: LedgerAccount) -> None:
    if ledger.status != LedgerStatus.PROPOSED:
        raise ProposalError(f"{ledger.name!r} is not a proposal awaiting a decision.")
