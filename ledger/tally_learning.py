"""What the assistant learns from a client's Tally bank history.

Every bank payment and receipt a Tally import wrote was placed by the accountant (the ledger Tally put the money against), so
each is a decision made by a person. This turns those
decisions into rules -- but by proportion, not by the last click: a payee whose payments all went to one ledger earns a rule,
a payee whose payments went to several earns none, a common first name earns little however often it appears, and a ledger
that takes most of the money anyway tells us less than a rare one. The arithmetic is ``classify.scoring``, the same as the
read-only rules report, so the two always agree.

A rule learned here never posts on its own: its confidence is kept under the 0.90 at which the system posts without asking, so
it places a row and a person still approves. Learning runs after the books are written and never as part of writing them, so a
failure here cannot undo an import.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from banking.models import BankAccount
from classify.engine import BARE_NAME_CONFIDENCE, LEARNED_PRIORITY, is_bare_name
from classify.models import (
    ClassificationRule,
    Direction,
    LedgerGroup,
    MatchType,
    Party,
    RuleSource,
)
from classify.narration import analyse, normalise
from classify.scoring import Evidence, confidence, first_word_counts, name_specificity, verdict
from classify.treatment import Treatment
from ledger.models import JournalEntry, VoucherType
from ledger.tally_parse import normal_name

#: Below the confidence at which a placement is posted without asking (``ledger.approval.auto_post``).
CEILING = 0.88


def _placements(client, run) -> list[tuple[str, bool, object]]:
    """``(narration, money went out, the ledger Tally put it against)`` for each bank payment or receipt the run wrote.

    A voucher with no bank line, with more than one, or whose other side is itself a bank or cash ledger (a transfer or a cash
    deposit) says nothing about a payee, so it is left out.
    """
    bank_names = {normal_name(n) for n in BankAccount.objects.filter(firm_id=client.firm_id, client=client).values_list("ledger_name", flat=True)}
    entries = JournalEntry.objects.filter(
        firm_id=client.firm_id, client=client, tally_voucher__run=run, voucher_type__in=[VoucherType.PAYMENT, VoucherType.RECEIPT]
    ).prefetch_related("lines__ledger_account")
    out = []
    for entry in entries:
        lines = list(entry.lines.all())
        banks = [ln for ln in lines if ln.ledger_account.group == LedgerGroup.BANK or normal_name(ln.ledger_account.name) in bank_names]
        others = [ln for ln in lines if ln not in banks]
        if len(banks) != 1 or not others:
            continue
        counter = max(others, key=lambda ln: abs(ln.signed_paise)).ledger_account
        if counter.is_bank_or_cash:
            continue
        out.append((entry.narration, banks[0].signed_paise < 0, counter))
    return out


def learn_rules(client, run, user) -> list[str]:
    """Write the rules this run's bank history justifies. Returns the new rules' ids, so an undo can take them back."""
    placements = _placements(client, run)
    by_payee: dict[tuple[str, str], Counter] = defaultdict(Counter)
    spelling: dict[str, str] = {}
    direction_total: Counter = Counter()
    direction_ledger: dict[str, Counter] = defaultdict(Counter)
    ledgers = {}
    for narration, money_out, ledger in placements:
        direction = Direction.DEBIT if money_out else Direction.CREDIT
        direction_total[direction] += 1
        direction_ledger[direction][ledger.pk] += 1
        ledgers[ledger.pk] = ledger
        name = analyse(narration).counterparty
        key = normalise(name) if name else ""
        if len(key) < 3:
            continue
        spelling.setdefault(key, name)
        by_payee[(key, direction)][ledger.pk] += 1

    if not by_payee:
        return []
    names = first_word_counts(
        list(spelling.values()) + list(Party.objects.filter(firm_id=client.firm_id, client=client).values_list("canonical_name", flat=True))
    )
    created_ids: list[str] = []
    for (key, direction), counts in by_payee.items():
        ranked = counts.most_common(2)
        ledger_id, agree = ranked[0]
        if len(ranked) > 1 and ranked[1][1] == agree:
            continue  # no clear favourite: a person will decide each time
        spec = name_specificity(spelling[key], names)
        base = direction_ledger[direction][ledger_id] / max(direction_total[direction], 1)
        score = confidence(Evidence(agree, sum(counts.values()), spec, base))
        if verdict(score) == "ask":
            continue
        cap = BARE_NAME_CONFIDENCE if is_bare_name(spelling[key]) else CEILING
        rule, created = ClassificationRule.objects.get_or_create(
            firm_id=client.firm_id,
            client=client,
            match_type=MatchType.PARTY_EQUALS,
            pattern=key,
            direction=direction,
            defaults={
                **Treatment(ledger=ledgers[ledger_id]).as_fields(),
                "source": RuleSource.LEARNED,
                "priority": LEARNED_PRIORITY,
                "confidence": min(score, cap),
                "created_by": user,
            },
        )
        if created:
            created_ids.append(str(rule.pk))
    return created_ids
