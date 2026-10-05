"""Learning from a person's decision, and applying the lesson to what is already there.

A CA who moves one entry from the ledger the AI chose to the ledger they know is
right has told the system something about the *payee*, not about that one
transaction. ``classify.engine.learn_rule_from`` already turns that into a rule
for the future. This module does the other half: it goes back through the books
that are still a working draft and applies the lesson to the entries the AI
placed on its own, so the CA corrects one and is not asked to correct the other
forty.

Two boundaries hold it in check, and both matter more than the feature:

* **A person's decision is never overridden.** Only rows the AI placed (by a
  rule or by the model) are revised. Whatever a person has decided stays, even
  if it disagrees with the new rule -- they may have had a reason.
* **Signed-off books are never touched.** An entry inside a locked period is
  skipped, quietly, because the database would refuse and because a lesson
  learned in October has no business rewriting September's signed books.

Everything it changes is marked (``EntryMarker.AI_REVISED`` on an entry,
``ai_revised`` on a row) so the CA can find what the AI did on its own, and
recorded in the change log with the previous state.
"""

from __future__ import annotations

from classify.models import ClassificationMethod, MatchType, TransactionClassification
from classify.narration import normalise
from ledger import editing
from ledger.models import BillAllocation, ChangeAction, EntryMarker, JournalEntry


def _live_entry(transaction_row):
    """The entry currently standing for a transaction, ignoring corrected ones."""
    for entry in JournalEntry.objects.filter(source_transaction=transaction_row).order_by("-created_at"):
        if not entry.is_superseded:
            return entry
    return None


def apply_learned_rule(client, rule, *, except_pk=None) -> int:
    """Apply ``rule`` to similar rows the AI placed, and return how many changed."""
    if rule is None or not rule.is_active or rule.match_type != MatchType.PARTY_EQUALS:
        return 0

    candidates = (
        TransactionClassification.objects.filter(
            firm_id=client.firm_id,
            transaction__bank_account__client=client,
            method__in=[ClassificationMethod.RULE, ClassificationMethod.LLM],
            ledger__isnull=False,
        )
        .exclude(ledger_id=rule.ledger_id)
        .exclude(pk=except_pk)
        .select_related("transaction__bank_account", "ledger")
    )

    revised = 0
    for row in candidates:
        # ``counterparty`` is stored as the bank spelled it, and the rule's
        # pattern is normalised, so compare like with like.
        if normalise(row.counterparty) != rule.pattern:
            continue
        if not _direction_fits(rule, row):
            continue

        entry = _live_entry(row.transaction)
        if entry is not None:
            if editing.is_locked(entry):
                continue
            # A payment on a party's account is a person's decision about which bills it settles. A lesson learned
            # from one payee never moves the AI's other entries onto that account, nor undoes a settlement.
            if rule.ledger.is_party_account or BillAllocation.objects.filter(line__entry=entry).exists():
                continue
            editing.revise_in_place(
                entry,
                rule.treatment,
                actor=None,
                method=ClassificationMethod.RULE,
                rule=rule,
                marker=EntryMarker.AI_REVISED,
                action=ChangeAction.AI_REVISED,
                note=f"Applied after a person placed this payee in {rule.ledger.name}.",
            )
        else:
            row.apply(
                rule.treatment,
                method=ClassificationMethod.RULE,
                confidence=rule.confidence,
                rule=rule,
            )
            row.save()
        TransactionClassification.objects.filter(pk=row.pk).update(ai_revised=True)
        revised += 1
    return revised


def _direction_fits(rule, row) -> bool:
    from classify.models import Direction

    if rule.direction == Direction.ANY:
        return True
    return (rule.direction == Direction.DEBIT) == row.transaction.is_debit


def learn_from_decision(classification, treatment, *, user, learn: bool = True):
    """A person placed a row. Learn from it, apply it, and post what is now certain.

    Returns ``(classification, rule, revised, auto_posted)``. The order matters:
    the rule is learned first, it then places any still-unplaced rows and revises
    the ones the AI got wrong, and only then are rows the AI is now very sure of
    posted -- so the books the CA sees next already reflect what they just taught.
    """
    from classify.engine import review
    from ledger.approval import auto_post_client

    client = classification.transaction.bank_account.client
    updated, rule = review(classification, treatment, user=user, learn=learn)
    revised = apply_learned_rule(client, rule, except_pk=classification.pk)
    auto_posted = auto_post_client(client)
    return updated, rule, revised, auto_posted


def learn_after_correction(entry, treatment, user):
    """A person corrected a posted entry. The same lesson, from the other direction."""
    from classify.engine import learn_rule_from, reclassify_unresolved
    from ledger.approval import auto_post_client

    classification = entry.source_transaction.classification
    client = entry.client
    rule = learn_rule_from(classification, treatment, user)
    if rule is None:
        return 0, 0
    reclassify_unresolved(client)
    revised = apply_learned_rule(client, rule, except_pk=classification.pk)
    return revised, auto_post_client(client)
