"""What a rule rests on, read back from the client's own placed rows.

A learned rule keeps no record of the decisions it came from, so the accountant checking it needs them looked up again: every
placed row whose payee reads as the rule's pattern, and where each of them went. Nothing here writes, and nothing is stored, so
it can never disagree with the rows it describes.
"""

from __future__ import annotations

from collections import Counter

from classify.models import ClassificationRule, Direction, MatchType, TransactionClassification
from classify.narration import analyse, normalise

#: Rows quoted back to the accountant. Enough to recognise the payee, few enough to read at a glance.
EXAMPLES = 5

#: Placed rows read per look. The newest are read first.
SCAN_LIMIT = 20000


def evidence_for(rule: ClassificationRule) -> dict:
    """The placed rows behind ``rule``, grouped by the ledger each went to.

    Only a rule keyed on the payee has evidence of this kind; a rule on the narration or the channel returns ``supported`` False,
    because the payee spelling is all the stored facts can be matched on.
    """
    if rule.match_type != MatchType.PARTY_EQUALS:
        return {"supported": False}

    placed = TransactionClassification.objects.filter(
        firm_id=rule.firm_id,
        transaction__bank_account__client_id=rule.client_id,
        ledger__isnull=False,
        is_self_transfer=False,
    )
    if rule.direction == Direction.DEBIT:
        placed = placed.filter(transaction__debit_paise__gt=0)
    elif rule.direction == Direction.CREDIT:
        placed = placed.filter(transaction__credit_paise__gt=0)

    # Rows the system placed itself kept the payee it read; rows a Tally import wrote did not, so it is read from the narration the
    # same way learning read it. Newest rows first, capped, so a very large client cannot make this slow.
    rows = placed.select_related("transaction", "ledger").order_by("-transaction__value_date")[
        :SCAN_LIMIT
    ]
    by_ledger: Counter = Counter()
    spellings: Counter = Counter()
    examples: list[dict] = []
    for c in rows:
        name = c.counterparty or analyse(c.transaction.narration).counterparty or ""
        if not name or normalise(name) != rule.pattern:
            continue
        by_ledger[c.ledger.name] += 1
        spellings[name] += 1
        if len(examples) < EXAMPLES:
            examples.append(
                {
                    "date": c.transaction.value_date.isoformat(),
                    "narration": c.transaction.narration[:160],
                    "paise": c.transaction.debit_paise or c.transaction.credit_paise,
                    "is_debit": c.transaction.debit_paise > 0,
                    "ledger": c.ledger.name,
                }
            )
    if not by_ledger:
        return {
            "supported": True,
            "payee": "",
            "total": 0,
            "to_this_ledger": 0,
            "elsewhere": [],
            "examples": [],
        }
    total = sum(by_ledger.values())
    mine = by_ledger.get(rule.ledger.name, 0)
    elsewhere = [
        {"ledger": name, "count": n}
        for name, n in by_ledger.most_common()
        if name != rule.ledger.name
    ]
    return {
        "supported": True,
        "payee": spellings.most_common(1)[0][0],
        "total": total,
        "to_this_ledger": mine,
        "elsewhere": elsewhere,
        "examples": examples,
    }
