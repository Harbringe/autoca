"""Money moving between the client's own bank accounts, found by pairing the two sides.

A transfer from one of a client's accounts to another is one event that appears twice: a withdrawal in the first statement and a deposit
in the second. Reading a single narration often cannot tell it apart from a payment to a stranger -- "DEP TFR UPI/CR/800755013962/SHANKA"
looks like a customer paying -- but the two sides carry the evidence between them: the same amount, on the same day, with the same UPI or
cheque reference printed on both, or one side naming the other's account number.

``pair_legs`` is pure: it takes the rows and says which debit goes with which credit, and how sure it is. ``pair_own_transfers`` applies
that to a client's unposted rows, placing each side in the other account's ledger so the entry is a Contra. It never touches a row a
person has decided, a row a rule placed, or a row already in the books.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

#: How far apart the two sides may be dated. Same day is the norm; a transfer made late in the evening is credited the next day.
WINDOW_DAYS = 1
#: Below this a pair is not claimed on amount and date alone: small equal amounts coincide too easily.
MIN_UNIQUE_PAISE = 1_000_000  # ₹10,000

#: Words a bank puts in the narration of a transfer, on either side.
_TRANSFER_WORDS = re.compile(r"\b(TFR|TRFR|TRANSFER|XFER|TRF)\b", re.IGNORECASE)
_LONG_NUMBER = re.compile(r"\d{9,}")


@dataclass(frozen=True)
class Leg:
    """One side of a possible transfer: a statement row."""

    id: str
    account_id: str
    date: datetime.date
    amount_paise: int
    is_debit: bool
    narration: str


@dataclass(frozen=True)
class Pair:
    debit: str
    credit: str
    #: 'reference' (the same number printed on both), 'named' (one side names the other's account), or 'unique' (only candidate).
    strength: str
    why: str


def _numbers(text: str) -> set[str]:
    """Long digit runs in a narration, without leading zeros so 0062139251173 and 62139251173 are one number."""
    return {n.lstrip("0") for n in _LONG_NUMBER.findall(text) if n.lstrip("0")}


def pair_legs(legs: list[Leg], own_numbers: dict[str, str] | None = None) -> list[Pair]:
    """The debits that go with credits in another of the client's accounts. Each row is in at most one pair.

    ``own_numbers`` maps an account id to its account number, when known, so a narration naming that number can be recognised.
    """
    own_numbers = {k: v.lstrip("0") for k, v in (own_numbers or {}).items() if v and v.lstrip("0")}
    debits = [leg for leg in legs if leg.is_debit]
    credits = [leg for leg in legs if not leg.is_debit]
    window = datetime.timedelta(days=WINDOW_DAYS)

    def candidates(leg: Leg, others: list[Leg]) -> list[Leg]:
        return [
            o for o in others
            if o.amount_paise == leg.amount_paise and o.account_id != leg.account_id and abs(o.date - leg.date) <= window
        ]

    scored: list[tuple[int, Pair]] = []
    for d in debits:
        options = candidates(d, credits)
        for c in options:
            shared = _numbers(d.narration) & _numbers(c.narration)
            if shared:
                scored.append((0, Pair(d.id, c.id, "reference", f"the same reference {sorted(shared)[0]} is on both")))
                continue
            names_other = (
                (own_numbers.get(c.account_id) and own_numbers[c.account_id] in _numbers(d.narration))
                or (own_numbers.get(d.account_id) and own_numbers[d.account_id] in _numbers(c.narration))
            )
            if names_other:
                scored.append((1, Pair(d.id, c.id, "named", "one side names the other account's number")))
                continue
            only_each_way = len(options) == 1 and len(candidates(c, debits)) == 1
            wording = _TRANSFER_WORDS.search(d.narration) and _TRANSFER_WORDS.search(c.narration)
            if only_each_way and wording and d.amount_paise >= MIN_UNIQUE_PAISE:
                scored.append((2, Pair(d.id, c.id, "unique", "the only matching amount on the other account, and both say transfer")))

    scored.sort(key=lambda sp: (sp[0], sp[1].debit, sp[1].credit))
    used: set[str] = set()
    out: list[Pair] = []
    for _, pair in scored:
        if pair.debit in used or pair.credit in used:
            continue
        used.update((pair.debit, pair.credit))
        out.append(pair)
    return out


#: Confidence of a placement made from a pair. Even a shared reference stays just under the 0.90 at which the system posts on its own,
#: so a pair is placed correctly and waits for a person to post it; a lone match is only a suggestion.
CONFIDENCE = {"reference": 0.88, "named": 0.88, "unique": 0.80}


def pair_own_transfers(client, *, apply: bool = True) -> list[Pair]:
    """Find a client's transfers between its own accounts among its unposted rows, and (with ``apply``) place both sides.

    Each side goes to the *other* account's ledger, so approving either one writes a Contra and the other is recognised as its twin.
    Only rows nobody has decided are used: not one a person placed, not one a rule placed, not one already in the books, and not one the
    assistant is reading at this moment. Safe to run again; rows already paired are not touched.
    """
    from classify.engine import _unposted
    from classify.models import ClassificationMethod, ModelState

    rows = list(
        _unposted(client)
        .filter(method__in=[ClassificationMethod.UNRESOLVED, ClassificationMethod.LLM])
        .exclude(model_state=ModelState.CLAIMED)
        .select_related("transaction__bank_account")
    )
    legs = [
        Leg(str(r.pk), str(r.transaction.bank_account_id), r.transaction.value_date, r.transaction.amount_paise, r.transaction.is_debit, r.transaction.narration)
        for r in rows
    ]
    own_numbers = {str(a.pk): a.account_number for a in client.bank_accounts.all()}
    pairs = pair_legs(legs, own_numbers)
    if not apply:
        return pairs

    from django.db import transaction

    applied: list[Pair] = []
    for pair in pairs:
        # A person may have placed, or the assistant claimed, either row since they were read. Each pair is re-read under a lock and
        # skipped unless both rows are still nobody's decision, so a human's choice is never overwritten.
        with transaction.atomic():
            fresh = {
                str(r.pk): r
                for r in _unposted(client)
                .filter(pk__in=[pair.debit, pair.credit], method__in=[ClassificationMethod.UNRESOLVED, ClassificationMethod.LLM])
                .exclude(model_state=ModelState.CLAIMED)
                .select_related("transaction__bank_account")
                .select_for_update(of=("self",))
            }
            if len(fresh) != 2:
                continue
            _place(fresh[pair.debit], fresh[pair.credit], pair)
            _place(fresh[pair.credit], fresh[pair.debit], pair)
            applied.append(pair)
    return applied


def _place(row, other, pair: Pair) -> None:
    """Put ``row`` in the other account's ledger, as one side of a transfer."""
    from classify.models import ClassificationMethod
    from classify.seeds import contra_ledger_for
    from classify.treatment import Treatment

    row.apply(
        Treatment(ledger=contra_ledger_for(other.transaction.bank_account)),
        method=ClassificationMethod.RULE,
        confidence=CONFIDENCE[pair.strength],
    )
    row.is_self_transfer = True
    row.rationale = f"A transfer between the client's own accounts: {pair.why}."
    row.model_state = None
    row.save(
        update_fields=[
            "ledger", "party", "rcm", "tds_section", "rule", "method", "confidence", "review_band", "needs_review",
            "suggested_ledger_name", "suggested_ledger_group", "book_narration", "is_self_transfer", "rationale", "model_state",
        ]
    )
