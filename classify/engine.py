"""Applying rules to transactions, and learning from the rows a person fixes.

The loop this implements:

    classify_statement()  places every row it can, queues the rest
    review()              a person places one queued row
                          -> a rule is minted from that decision
                          -> reclassify_unresolved() applies it to the backlog

That last step is what makes the queue shrink. A person who places one of nine
identical BHIM cashback credits has placed all nine; making them do it nine
times is how a tool gets abandoned.

Two properties are deliberate and worth keeping:

* **Matching is ordered, never first-match-wins over an arbitrary queryset.**
  Two rules can legitimately claim one row -- one for a payee and one for the
  channel it arrived on -- and which wins has to be a property of the rules,
  not of how the database felt like returning them. Both are always rules of
  the same client: rules do not travel between clients, because a ledger
  belongs to one client and placing a row is naming a ledger.
* **Every decision carries a confidence and a provenance.** The review screen
  sorts by confidence, and that ordering is what turns an hour of checking into
  minutes. A suggestion with no confidence attached is a guess wearing a
  uniform.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from classify.models import (
    ClassificationMethod,
    ClassificationRule,
    Direction,
    MatchType,
    RuleSource,
    TransactionClassification,
    Party,
)
from classify.narration import NarrationFacts, analyse, normalise
from classify.parties import Kind, PartyBook, candidates_as_json, confirm_alias
from classify.treatment import ReviewBand, Treatment, band_for

#: Learned rules outrank seeds but sit below anything written by hand, so a
#: deliberate rule is never overridden by an inference from a single click.
LEARNED_PRIORITY = 500

#: Default confidence by match type. A rule learned from a person naming this
#: exact payee is a far stronger claim than one matching every transaction on a
#: channel, and the review screen should say so.
CONFIDENCE_BY_MATCH = {
    MatchType.PARTY_EQUALS: 0.95,
    MatchType.PARTY_CONTAINS: 0.85,
    MatchType.NARRATION_CONTAINS: 0.85,
    MatchType.REGEX: 0.85,
    # A channel rule is a generalisation about how money moved, not about who it
    # moved to. Right often enough to suggest, never certain enough to assert --
    # except for the seeded ones, which describe what the bank itself did.
    MatchType.CHANNEL_IS: 0.80,
}


def default_confidence(match_type: str, source: str) -> float:
    """What a fresh rule of this kind should claim.

    Seeded rules describe the bank's own behaviour -- interest it paid, charges
    it levied -- and those mean the same thing in every set of books, so they
    assert rather than suggest even though they match on a channel.
    """
    if source == RuleSource.SEED:
        return 0.95
    return CONFIDENCE_BY_MATCH.get(match_type, 0.85)


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


@dataclass(frozen=True)
class ReviewSummary:
    """The "which entries need looking at" view the requirements document asks for."""

    high: int
    advised: int
    judgement: int

    @property
    def total(self) -> int:
        return self.high + self.advised + self.judgement

    @property
    def bulk_approvable(self) -> int:
        return self.high


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def rules_for(client) -> list[ClassificationRule]:
    """Active rules of ``client``, strongest first.

    Only this client's rules. Rules are not shared between clients even within
    one firm: a rule names a ledger, a ledger belongs to one client, so a rule
    borrowed from a sibling client would book this client's money into a set of
    books that is not theirs.

    Ordering, most significant first:

    * higher priority beats lower.
    * a longer pattern beats a shorter one, because it is the more specific
      claim about the same text.
    """
    candidates = ClassificationRule.objects.filter(
        client=client, is_active=True
    ).select_related("ledger", "party")
    return sorted(candidates, key=lambda rule: (rule.priority, len(rule.pattern)), reverse=True)


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
        pending, rules, account.account_holder, _own_account_numbers(client), statement.firm_id,
        client=client,
    )


def reclassify_unresolved(client, *, rules=None) -> ClassifyResult:
    """Re-run the rules over the review queue only.

    Called after a rule is learned. Never touches a row that already has a
    ledger: a new rule is not authority to overturn a person's judgement.
    """
    rules = rules if rules is not None else rules_for(client)

    queued = unresolved_for(client).select_related("transaction__bank_account__client")

    placed = 0
    for classification in queued:
        txn = classification.transaction
        rule = first_matching_rule(_facts_for(classification), txn.is_debit, rules)
        if rule is None:
            continue
        classification.apply(
            rule.treatment,
            method=ClassificationMethod.RULE,
            confidence=rule.confidence,
            rule=rule,
        )
        classification.save(
            update_fields=[
                "ledger",
                "party",
                "rcm",
                "tds_section",
                "rule",
                "method",
                "confidence",
                "review_band",
                "needs_review",
            ]
        )
        _record_hits([rule])
        placed += 1

    return ClassifyResult(placed=placed, queued=len(queued) - placed)


# ---------------------------------------------------------------------------
# Review and learning
# ---------------------------------------------------------------------------


@db_transaction.atomic
def review(classification, treatment, user=None, *, learn: bool = True):
    """Place a queued row, and learn the rule its treatment implies.

    ``treatment`` may be a :class:`~classify.treatment.Treatment` or a bare
    ledger, which is the common case from a UI where the reviewer only changed
    the ledger head.

    ``learn`` exists for the case a person means "this one row only" -- a
    refund, a one-off that happens to name a regular payee. Defaulting it to
    True is the right trade: an over-eager rule shows up as more rows in the
    wrong ledger, which is visible and correctable, while never learning shows
    up as a queue that never gets shorter, which just looks like the tool not
    working.
    """
    treatment = _coerce_treatment(treatment)
    classification.resolve(treatment, user)
    _teach_party(classification, treatment, user)
    if not learn:
        return classification, None

    rule = learn_rule_from(classification, treatment, user)
    if rule is not None:
        reclassify_unresolved(classification.transaction.bank_account.client)
    return classification, rule


def _teach_party(classification, treatment, user) -> None:
    """Remember the spelling a person just placed, so it is never asked twice.

    The same move as ``learn_rule_from``, one level down: that turns a decision
    about *where a payee's money goes* into a rule; this turns a decision about
    *who the payee is* into an alias. Done even when ``learn`` is off, because
    "put this one row in Repairs" is a statement about the ledger, while "this
    is Ramesh Traders" stays true whichever ledger the row lands in.
    """
    if treatment.party is not None:
        confirm_party(classification, treatment.party, user)


def confirm_party(classification, party, user=None) -> None:
    """A person says who this row's payee is. Remember it, and apply it.

    Records the spelling as an alias, marks the row confirmed, and then does the
    part that makes the queue shrink: every other unposted row for the same
    spelling is now a recognised payee, not a suggestion, because a person has
    just settled the question for that spelling. Rows already posted are left
    alone -- their entries carry their own party and are not this function's to
    rewrite.

    Does not touch the row's ledger or how it was classified: who the payee is
    and where the money goes are separate decisions.
    """
    client = classification.transaction.bank_account.client
    facts = _facts_for(classification)
    spelling = facts.counterparty if not facts.is_self_transfer else ""
    key = normalise(spelling)

    if key and key != normalise(party.canonical_name):
        confirm_alias(client, party, spelling, user=user)

    classification.party = party
    classification.party_resolution = "CONFIRMED"
    classification.party_candidates = []
    classification.save(update_fields=["party", "party_resolution", "party_candidates"])

    if not key:
        return
    for row in _unposted(client).filter(
        party__isnull=True, party_resolution__in=["", "NEW", "CANDIDATE"]
    ).exclude(pk=classification.pk):
        if normalise(row.counterparty) == key:
            row.party = party
            row.party_resolution = "AUTO"
            row.party_candidates = []
            row.save(update_fields=["party", "party_resolution", "party_candidates"])


def learn_rule_from(classification, treatment, user=None) -> ClassificationRule | None:
    """Derive a reusable rule from one human decision.

    Keys on the counterparty, not on the narration. A narration carries a
    per-transaction reference number, so a rule written against one would match
    exactly the row it was learned from and nothing else -- the rule table would
    grow one row per transaction and never converge. The counterparty is the
    part that repeats.

    Returns None when there is nothing generalisable to learn, rather than
    inventing a rule that will misfire.
    """
    treatment = _coerce_treatment(treatment)
    if treatment.ledger is not None and treatment.ledger.is_bank_or_cash:
        # A movement between the client's own accounts names the account holder, not the other
        # account. A rule keyed on that name cannot tell which of the client's accounts a later
        # transfer went to, and would post it to the wrong bank without asking. Each such
        # transfer is a decision of its own.
        return None

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
            **treatment.as_fields(),
            "source": RuleSource.LEARNED,
            "priority": LEARNED_PRIORITY,
            "confidence": default_confidence(MatchType.PARTY_EQUALS, RuleSource.LEARNED),
            "created_by": user,
        },
    )
    if not created and not treatment.matches(rule):
        # The person changed their mind about this payee -- a different ledger,
        # or the same ledger now flagged reverse-charge. Their latest decision
        # is the one that stands, on all four counts rather than just the one
        # they happened to click.
        for field, value in treatment.as_fields().items():
            setattr(rule, field, value)
        rule.is_active = True
        rule.save(update_fields=["ledger", "party", "rcm", "tds_section", "is_active"])
    return rule


def party_for(client, name: str, *, rcm: bool = False, tds_section: str = "") -> Party:
    """Find or open the party record for a counterparty name.

    Matched on the normalised name, so the bank's inconsistent spacing and case
    do not produce three parties for one payee.
    """
    canonical = " ".join(name.split())
    existing = next(
        (
            party
            for party in Party.objects.filter(firm_id=client.firm_id, client=client)
            if normalise(party.canonical_name) == normalise(canonical)
        ),
        None,
    )
    if existing is not None:
        return existing

    return Party.objects.create(
        firm_id=client.firm_id,
        client=client,
        canonical_name=canonical,
        rcm_default=rcm,
        tds_section=tds_section,
    )


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------


def review_queue(client, band: str | None = None):
    """Everything still to be dealt with, optionally one band at a time.

    "Still to be dealt with" means **not yet posted to the ledger**, not "not
    yet looked at". Those came apart the first time this pipeline was run end to
    end: placing a row cleared ``needs_review``, so it vanished from the queue
    while having no journal entry behind it, and nothing surfaced the gap. A
    transaction that a person has placed but nobody has approved is not finished
    work, and a queue that hides it is how a month closes short.

    Ordered by confidence descending, so the rows the system is surest about --
    the ones eligible for bulk approval -- come first, and the genuinely
    ambiguous ones sit at the bottom where they belong.
    """
    queue = (
        _unposted(client)
        .select_related("transaction__bank_account", "ledger", "party")
        .order_by("-confidence", "-transaction__value_date")
    )
    return queue.filter(review_band=band) if band else queue


def unresolved_for(client):
    """Rows nobody has placed in a ledger yet, most recent first."""
    return (
        _unposted(client)
        .filter(ledger__isnull=True)
        .select_related("transaction")
        .order_by("-transaction__value_date")
    )


def pending_approval(client):
    """Rows with a ledger, waiting for a senior CA to post them.

    The other half of the queue, and the half that used to be invisible.
    """
    return (
        _unposted(client)
        .filter(ledger__isnull=False)
        .select_related("transaction__bank_account", "ledger", "party")
        .order_by("-confidence", "-transaction__value_date")
    )


def not_decided_by_a_person(client, statement=None):
    """Unposted rows whose treatment came from a rule, the model, or nothing.

    What the model may be asked about again. A person's decision and a posted
    entry are both off limits: the first is authority, the second is immutable.
    """
    rows = _unposted(client).exclude(method=ClassificationMethod.REVIEWED)
    if statement is not None:
        rows = rows.filter(transaction__statement=statement)
    return rows.order_by("-transaction__value_date")


def _unposted(client):
    """Classifications with no live journal entry behind them.

    A superseded entry does not count as posted: its correction is what stands,
    and the correction carries its own classification.

    Written as an explicit subquery rather than a chained ``exclude()`` across
    the relation. ``exclude(transaction__journal_entries__superseded_by_set__isnull=True)``
    reads as "no live entry" and is not -- Django's exclude semantics across two
    multi-valued relations quietly removed every row, which showed up as an
    empty review queue the first time this ran against a real statement.
    """
    from ledger.models import JournalEntry

    posted = JournalEntry.objects.filter(
        firm_id=client.firm_id, superseded_by_set__isnull=True
    ).values("source_transaction_id")

    return TransactionClassification.objects.filter(
        firm_id=client.firm_id,
        transaction__bank_account__client=client,
        # The other side of an own-account transfer is done once its twin is posted.
        mirrored_entry_id__isnull=True,
    ).exclude(transaction_id__in=posted)


def review_summary(client) -> ReviewSummary:
    """How much work is waiting, split by how much thought each row needs."""
    counts = Counter(review_queue(client).values_list("review_band", flat=True))
    return ReviewSummary(
        high=counts.get(ReviewBand.HIGH, 0),
        advised=counts.get(ReviewBand.ADVISED, 0),
        judgement=counts.get(ReviewBand.JUDGEMENT, 0),
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _coerce_treatment(value) -> Treatment:
    return value if isinstance(value, Treatment) else Treatment(ledger=value)


def _classify_rows(transactions, rules, holder, own_accounts, firm_id, *, client) -> ClassifyResult:
    placed = queued = 0
    fresh = []
    hits = []
    book = PartyBook(client)

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
            row.confidence = 0.0
            row.review_band = band_for(0.0)
            queued += 1
        else:
            row.apply(
                rule.treatment,
                method=ClassificationMethod.RULE,
                confidence=rule.confidence,
                rule=rule,
            )
            hits.append(rule)
            placed += 1

        # What the system can say about *who* this is, whether or not a rule
        # decided *where it goes* -- the two are separate questions, and a row
        # placed by a rule about the payee's category still deserves to be told
        # that its payee looks like a known party.
        if facts.counterparty and not facts.is_self_transfer:
            found = book.resolve(counterparty=facts.counterparty)
            row.party_resolution = found.kind
            row.party_candidates = candidates_as_json(found)
            # Only a fact fills the party in unasked, and only where nothing has
            # already named one: a rule's own choice of party stands.
            if found.kind == Kind.AUTO and row.party_id is None:
                row.party = found.party
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

    The same rule usually fires many times in one statement -- nine BHIM
    cashbacks is one rule and nine hits -- so this adds a count rather than
    setting one, or a whole statement's worth of hits registers as a single
    firing.
    """
    counted = Counter(rule.pk for rule in rules)
    now = timezone.now()
    for pk, times in counted.items():
        ClassificationRule.objects.filter(pk=pk).update(
            hit_count=F("hit_count") + times, last_hit_at=now
        )
