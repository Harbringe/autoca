"""Applying rules to transactions, and learning from the rows a person fixes.

The loop this implements:

    classify_statement()  places every row it can, queues the rest
    review()              a person places one queued row
                          -> a rule is minted from that decision
                          -> reclassify_unresolved() applies it to the backlog

That last step is what makes the queue shrink. A person who places one of
nineteen identical BHIM cashback credits has placed all nineteen; making them do
it nineteen times is how a tool gets abandoned.

Matching is deterministic and ordered, never first-match-wins over an arbitrary
queryset order. Two rules can legitimately claim one row -- a client rule for a
payee and a firm-wide rule for the channel it arrived on -- and which of them
wins has to be a property of the rules, not of how the database felt like
returning them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db import transaction as db_transaction
from django.db.models import F, Q
from django.utils import timezone

from classify.models import (
    ClassificationMethod,
    ClassificationRule,
    Direction,
    LedgerAccount,
    MatchType,
    RuleSource,
    TransactionClassification,
)
from classify.narration import NarrationFacts, analyse, normalise


@dataclass(frozen=True)
class ClassifyResult:
    placed: int
    queued: int

    @property
    def total(self) -> int:
        return self.placed + self.queued

    @property
    def hit_rate(self) -> float:
        return self.placed / self.total if self.total else 0.0


def rules_for(client) -> list[ClassificationRule]:
    """Active rules that may apply to ``client``, strongest first.

    Ordering, most significant first:

    * a client-specific rule beats a firm-wide one, always. A firm-wide rule is
      a generalisation; a client rule is a statement about this client's books,
      and the specific statement wins.
    * higher priority beats lower.
    * a longer pattern beats a shorter one, because it is the more specific
      claim about the same text.
    """
    candidates = ClassificationRule.objects.filter(
        Q(client=client) | Q(client__isnull=True), is_active=True
    ).select_related("ledger")
    return sorted(
        candidates,
        key=lambda rule: (rule.client_id is not None, rule.priority, len(rule.pattern)),
        reverse=True,
    )


def first_matching_rule(facts: NarrationFacts, is_debit: bool, rules) -> ClassificationRule | None:
    for rule in rules:
        if rule.matches(facts, is_debit):
            return rule
    return None


def classify_statement(statement, *, rules=None) -> ClassifyResult:
    """Classify every unclassified row of ``statement``.

    Idempotent: rows that already carry a classification are left alone, so
    re-running after a rule change does not overwrite a person's decision. Use
    :func:`reclassify_unresolved` to apply new rules to the backlog.
    """
    account = statement.bank_account
    client = account.client
    rules = rules if rules is not None else rules_for(client)

    pending = statement.transactions.filter(classification__isnull=True)
    return _classify_rows(
        pending, rules, account.account_holder, _own_account_numbers(client), statement.firm_id
    )


def reclassify_unresolved(client, *, rules=None) -> ClassifyResult:
    """Re-run the rules over the review queue only.

    Called after a rule is learned. Never touches a row that already has a
    ledger: a new rule is not authority to overturn a person's judgement.
    """
    rules = rules if rules is not None else rules_for(client)

    queued = TransactionClassification.objects.filter(
        firm_id=client.firm_id,
        needs_review=True,
        ledger__isnull=True,
        transaction__bank_account__client=client,
    ).select_related("transaction__bank_account__client")

    placed = 0
    for classification in queued:
        txn = classification.transaction
        facts = _facts_for(classification)
        rule = first_matching_rule(facts, txn.is_debit, rules)
        if rule is None:
            continue
        classification.ledger = rule.ledger
        classification.rule = rule
        classification.method = ClassificationMethod.RULE
        classification.confidence = 1.0
        classification.needs_review = False
        classification.save(
            update_fields=["ledger", "rule", "method", "confidence", "needs_review"]
        )
        _record_hits([rule])
        placed += 1

    return ClassifyResult(placed=placed, queued=len(queued) - placed)


@db_transaction.atomic
def review(classification, ledger: LedgerAccount, user=None, *, learn: bool = True):
    """Place a queued row in a ledger, and learn the rule it implies.

    ``learn`` exists for the case a person means "this one row only" -- a
    refund, a one-off that happens to name a regular payee. Defaulting it to
    True is the right trade: an over-eager rule shows up as more rows in the
    wrong ledger, which is visible and correctable, while never learning shows
    up as a queue that never gets shorter, which just looks like the tool not
    working.
    """
    classification.resolve(ledger, user)
    if not learn:
        return classification, None

    rule = learn_rule_from(classification, ledger, user)
    if rule is not None:
        reclassify_unresolved(classification.transaction.bank_account.client)
    return classification, rule


def learn_rule_from(classification, ledger: LedgerAccount, user=None) -> ClassificationRule | None:
    """Derive a reusable rule from one human decision.

    Keys on the counterparty, not on the narration. A narration carries a
    per-transaction reference number, so a rule written against one would match
    exactly the row it was learned from and nothing else -- the rule table would
    grow one row per transaction and never converge. The counterparty is the
    part that repeats.

    Returns None when there is nothing generalisable to learn, rather than
    inventing a rule that will misfire.
    """
    facts = _facts_for(classification)
    if not facts.counterparty:
        return None

    pattern = normalise(facts.counterparty)
    if len(pattern) < 3:
        return None

    client = classification.transaction.bank_account.client
    rule, created = ClassificationRule.objects.get_or_create(
        firm_id=classification.firm_id,
        client=client,
        match_type=MatchType.PARTY_EQUALS,
        pattern=pattern,
        direction=Direction.ANY,
        defaults={
            "ledger": ledger,
            "source": RuleSource.LEARNED,
            "priority": LEARNED_PRIORITY,
            "created_by": user,
        },
    )
    if not created and rule.ledger_id != ledger.pk:
        # The person changed their mind about this payee. Their latest decision
        # is the one that stands.
        rule.ledger = ledger
        rule.is_active = True
        rule.save(update_fields=["ledger", "is_active"])
    return rule


#: Learned rules outrank seeds but sit below anything written by hand, so a
#: deliberate rule is never overridden by an inference from a single click.
LEARNED_PRIORITY = 500


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _classify_rows(transactions, rules, holder, own_accounts, firm_id) -> ClassifyResult:
    placed = queued = 0
    fresh = []
    hits = []

    for txn in transactions.select_related("bank_account"):
        facts = analyse(txn.narration, holder, own_accounts)
        rule = first_matching_rule(facts, txn.is_debit, rules)

        row = TransactionClassification(
            firm_id=firm_id,
            transaction=txn,
            channel=facts.channel,
            counterparty=facts.counterparty[:255],
            is_self_transfer=facts.is_self_transfer,
        )
        if rule is None:
            row.method = ClassificationMethod.UNRESOLVED
            row.needs_review = True
            queued += 1
        else:
            row.ledger = rule.ledger
            row.rule = rule
            row.method = ClassificationMethod.RULE
            row.confidence = 1.0
            row.needs_review = False
            hits.append(rule)
            placed += 1
        fresh.append(row)

    TransactionClassification.objects.bulk_create(fresh)
    _record_hits(hits)
    return ClassifyResult(placed=placed, queued=queued)


def _facts_for(classification) -> NarrationFacts:
    account = classification.transaction.bank_account
    return analyse(
        classification.transaction.narration,
        account.account_holder,
        _own_account_numbers(account.client),
    )


def _own_account_numbers(client) -> list[str]:
    """The client's own account numbers, for spotting contra transfers.

    Decrypted one row at a time rather than selected as a column, because the
    stored value is ciphertext. There are a handful of accounts per client, so
    the cost is nil -- and the alternative, a plaintext column to make this
    query convenient, is exactly the shortcut the encryption exists to prevent.
    """
    return [account.account_number for account in client.bank_accounts.all()]


def _record_hits(rules) -> None:
    """Count firings in the database, not from a stale in-memory value.

    The same rule usually fires many times in one statement -- nineteen BHIM
    cashbacks is one rule and nineteen hits -- so this has to add a count rather
    than set one, or a whole statement's worth of hits registers as a single
    firing.
    """
    counted = Counter(rule.pk for rule in rules)
    now = timezone.now()
    for pk, times in counted.items():
        ClassificationRule.objects.filter(pk=pk).update(
            hit_count=F("hit_count") + times, last_hit_at=now
        )


def unresolved_for(client):
    """The review queue, most recent first."""
    return (
        TransactionClassification.objects.filter(
            firm_id=client.firm_id, needs_review=True, transaction__bank_account__client=client
        )
        .select_related("transaction")
        .order_by("-transaction__value_date")
    )
