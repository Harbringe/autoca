"""A read-only report of how well a client's learned rules and parties stand on their own history.

    python manage.py rules_report --firm <uuid> --client "Acme"

Writes nothing. For each active learned rule it counts the decisions a person made for that payee and direction, scores the rule with
``classify.scoring``, and says whether the history would let it place rows on its own, only suggest, or leave them to a person. For
parties it counts the names that look like bare first names with nothing behind them, and the names so alike they are probably one.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand, CommandError

from classify.models import (
    ClassificationMethod,
    ClassificationRule,
    Direction,
    Party,
    RuleSource,
    TransactionClassification,
)
from classify.narration import normalise
from classify.scoring import Evidence, confidence, first_word_counts, name_specificity, verdict
from core.db.session import firm_context
from core.models import Client

SIMILAR = 0.88
SHOW = 12


class Command(BaseCommand):
    help = "Report (read-only) which learned rules and parties the history does not support."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True)
        parser.add_argument("--client", required=True)

    def handle(self, *args, firm, client, **options):
        with firm_context(firm):
            try:
                record = Client.objects.get(firm_id=firm, name=client)
            except Client.DoesNotExist:
                raise CommandError(f"No client called {client!r} in that firm.") from None
            self._rules(firm, record)
            self._parties(firm, record)

    def _rules(self, firm, record):
        decided = TransactionClassification.objects.filter(
            firm_id=firm, transaction__bank_account__client=record, method=ClassificationMethod.REVIEWED, ledger__isnull=False
        ).select_related("transaction")
        by_payee: dict[tuple[str, str], Counter] = defaultdict(Counter)
        direction_total: Counter = Counter()
        direction_ledger: dict[str, Counter] = defaultdict(Counter)
        for row in decided:
            d = Direction.DEBIT if row.transaction.is_debit else Direction.CREDIT
            direction_total[d] += 1
            direction_ledger[d][row.ledger_id] += 1
            if row.counterparty:
                by_payee[(normalise(row.counterparty), d)][row.ledger_id] += 1
        names = first_word_counts(p.canonical_name for p in Party.objects.filter(firm_id=firm, client=record))
        rules = list(
            ClassificationRule.objects.filter(firm_id=firm, client=record, source=RuleSource.LEARNED, is_active=True).select_related("ledger", "party")
        )
        tally: Counter = Counter()
        sample: dict[str, list[str]] = defaultdict(list)
        for rule in rules:
            counts = by_payee.get((rule.pattern, rule.direction), Counter())
            total = sum(counts.values())
            agree = counts.get(rule.ledger_id, 0)
            # The match key has no spaces, so the name is judged by the party's spelling where the rule has one.
            spec = name_specificity(rule.party.canonical_name if rule.party_id else rule.pattern, names)
            base = direction_ledger[rule.direction].get(rule.ledger_id, 0) / max(direction_total[rule.direction], 1)
            v = verdict(confidence(Evidence(agree, total, spec, base)))
            tally[v] += 1
            if v != "place" and len(sample[v]) < SHOW:
                sample[v].append(f"{rule.pattern} ({rule.get_direction_display()}) -> {rule.ledger.name}: {agree} of {total} decisions, used {rule.hit_count}")
        self.stdout.write(f"Learned rules in use: {len(rules)}")
        for v in ("place", "suggest", "ask"):
            self.stdout.write(f"  {v}: {tally[v]}")
        for v in ("suggest", "ask"):
            self.stdout.write(f"Examples that would only {v}:")
            for line in sample[v]:
                self.stdout.write(f"  {line}")

    def _parties(self, firm, record):
        parties = list(Party.objects.filter(firm_id=firm, client=record))
        used = Counter(
            TransactionClassification.objects.filter(firm_id=firm, transaction__bank_account__client=record, party__isnull=False)
            .values_list("party_id", flat=True)
        )
        bare = [p for p in parties if len(p.canonical_name.split()) == 1 and not p.gstin_hash]
        weak = [p for p in bare if used.get(p.pk, 0) < 3]
        self.stdout.write(f"\nParties: {len(parties)}")
        self.stdout.write(f"  one-word names with no GSTIN: {len(bare)}; of them seen on fewer than 3 rows: {len(weak)}")
        for p in weak[:SHOW]:
            self.stdout.write(f"    {p.canonical_name} (rows {used.get(p.pk, 0)})")
        keys = sorted(((normalise(p.canonical_name), p) for p in parties), key=lambda kp: kp[0])
        pairs = []
        for i, (a, pa) in enumerate(keys):
            for b, pb in keys[i + 1 : i + 6]:
                if a and b and SequenceMatcher(None, a, b).ratio() >= SIMILAR:
                    pairs.append((pa.canonical_name, pb.canonical_name))
        self.stdout.write(f"  pairs of names so alike they are probably one party: {len(pairs)}")
        for a, b in pairs[:SHOW]:
            self.stdout.write(f"    {a}  ~  {b}")
