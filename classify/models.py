"""Ledgers, the rules that map transactions onto them, and the results.

The product this supports is narrow and specific: a firm uploads a statement,
the system proposes a ledger for every row, and a person looks only at the rows
it could not place. Every decision that person makes becomes a rule, so the
queue shrinks each month instead of staying the same size. A classifier that
cannot learn is a classifier a firm stops using in week three.

Three things follow from that, and they are why the schema looks like this:

* A classification **points at** a transaction, it never edits one. The bank's
  record of what happened and the firm's opinion about what it means are
  separate facts, and re-classifying must not rewrite the first.
* Every classification records *how* it was reached. "The rule that put 1,200
  rows in Advance Tax was wrong" is a question a firm will ask, and answering it
  needs the link, not a recomputation against rules that have since changed.
* A rule is scoped to a client by default and can be promoted to the firm. Payee
  meanings are not universal -- one firm's ``ZERODHA`` is a broker's fee, the
  next firm's is the client's own investment -- and a rule table shared across
  clients by default would quietly cross-contaminate their books.
"""

from __future__ import annotations

import hashlib
import re

from django.db import models
from django.utils import timezone

from banking.models import StatementTransaction
from classify.treatment import ReviewBand, TdsSection, Treatment, band_for
from core.crypto import blind_index, decrypt_text_for_firm, encrypt_for_firm
from core.models import Client, FirmScopedModel, User, UUIDModel

#: Encryption context domain for identifiers held in this app.
CRYPTO_PURPOSE = "classify.vendor"


class LedgerGroup(models.TextChoices):
    """Tally's top-level groups, as far as this system needs to know them.

    Stored on the ledger because the voucher exporter needs it: a transfer to
    the client's own account at another bank is a Contra, and the only thing
    that distinguishes it from a Payment is the group of the other ledger.
    """

    BANK = "BANK", "Bank Accounts"
    CASH = "CASH", "Cash-in-Hand"
    DEBTOR = "DEBTOR", "Sundry Debtors"
    CREDITOR = "CREDITOR", "Sundry Creditors"
    INDIRECT_EXPENSE = "INDIRECT_EXPENSE", "Indirect Expenses"
    DIRECT_EXPENSE = "DIRECT_EXPENSE", "Direct Expenses"
    INDIRECT_INCOME = "INDIRECT_INCOME", "Indirect Incomes"
    DIRECT_INCOME = "DIRECT_INCOME", "Direct Incomes"
    DUTIES_AND_TAXES = "DUTIES_AND_TAXES", "Duties & Taxes"
    LOAN = "LOAN", "Loans (Liability)"
    INVESTMENT = "INVESTMENT", "Investments"
    CAPITAL = "CAPITAL", "Capital Account"
    SUSPENSE = "SUSPENSE", "Suspense A/c"


class LedgerStatus(models.TextChoices):
    """Whether a ledger may carry entries yet.

    A model may *propose* a ledger the client's chart lacks; it becomes usable
    only when a CA accepts it. Rejected proposals are kept so the same name is
    not proposed again next month.
    """

    ACTIVE = "ACTIVE", "In use"
    PROPOSED = "PROPOSED", "Proposed, awaiting a CA"
    REJECTED = "REJECTED", "Rejected by a CA"


class LedgerAccount(UUIDModel, FirmScopedModel):
    """A ledger in the client's Tally company.

    ``name`` must match Tally exactly. Tally creates a ledger it does not
    recognise rather than rejecting the import, so a typo does not fail loudly --
    it silently splits a year of entries across "Advance Tax" and "Advance tax".
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="ledgers")
    name = models.CharField(max_length=255)
    group = models.CharField(
        max_length=32, choices=LedgerGroup.choices, default=LedgerGroup.SUSPENSE
    )
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=LedgerStatus.choices, default=LedgerStatus.ACTIVE)
    proposal_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "classify_ledger_account"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "name"], name="uniq_ledger_name_per_client"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_bank_or_cash(self) -> bool:
        """True when posting against this ledger makes the voucher a Contra."""
        return self.group in {LedgerGroup.BANK, LedgerGroup.CASH}

    @property
    def is_proposed(self) -> bool:
        return self.status == LedgerStatus.PROPOSED


class Vendor(UUIDModel, FirmScopedModel):
    """A party the client transacts with.

    Separate from the ledger head because they answer different questions. The
    ledger says what kind of expense it was; the vendor says who it was with,
    and "how much did we pay this vendor this year" is a question a firm is
    asked constantly and cannot answer from ledger heads alone.

    The vendor is also where reverse-charge and TDS defaults live, because those
    are properties of *who you are paying*, not of the category you booked it
    under. A goods transport agency is reverse-charge whether the payment lands
    in Freight or in Direct Expenses.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="vendors")
    canonical_name = models.CharField(max_length=255)

    #: A stable stand-in for the name -- "V" plus a short hash. When a narration
    #: is sent to a language model for classification, known vendors are
    #: replaced by this, so the model sees the shape of the transaction without
    #: the counterparty's identity. The mapping back happens server-side.
    alias_token = models.CharField(max_length=24, db_index=True)

    gstin_enc = models.BinaryField(blank=True, null=True)
    gstin_hash = models.CharField(max_length=64, blank=True, db_index=True)

    #: Reverse charge applies to this vendor by default. Learned once per client
    #: and then applied, rather than re-decided every month.
    rcm_default = models.BooleanField(default=False)
    #: TDS section that normally applies to payments to this vendor, if any.
    tds_section = models.CharField(max_length=16, blank=True, choices=TdsSection.CHOICES)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "classify_vendor"
        ordering = ["canonical_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "canonical_name"], name="uniq_vendor_name_per_client"
            ),
        ]

    def __str__(self) -> str:
        return self.canonical_name

    def save(self, *args, **kwargs):
        if not self.alias_token:
            self.alias_token = self.make_alias(self.canonical_name, self.firm_id)
        return super().save(*args, **kwargs)

    @staticmethod
    def make_alias(name: str, firm_id) -> str:
        """A stable pseudonym, unique within a firm and meaningless outside it."""
        seed = f"{firm_id}|{name.strip().upper()}".encode()
        return "V" + hashlib.sha256(seed).hexdigest()[:10].upper()

    @property
    def gstin(self) -> str:
        if not self.gstin_enc:
            return ""
        return decrypt_text_for_firm(bytes(self.gstin_enc), self.firm_id, CRYPTO_PURPOSE)

    def set_gstin(self, gstin: str) -> None:
        """Store the GSTIN encrypted, with a blind index for reconciliation.

        GST reconciliation matches purchase-register rows to GSTR-2B rows on
        vendor GSTIN. That join has to work on ciphertext that is different
        every time, which is what the hash column is for.
        """
        gstin = (gstin or "").strip().upper()
        if not gstin:
            self.gstin_enc = None
            self.gstin_hash = ""
            return
        self.gstin_enc = encrypt_for_firm(gstin, self.firm_id, CRYPTO_PURPOSE)
        self.gstin_hash = blind_index(gstin, self.firm_id, CRYPTO_PURPOSE)


class MatchType(models.TextChoices):
    #: Normalised counterparty equals the pattern. The safest rule, and what
    #: learning from a human decision produces.
    PARTY_EQUALS = "PARTY_EQUALS", "Counterparty is exactly"
    #: Normalised counterparty contains the pattern. For payees whose name the
    #: bank truncates differently from one channel to the next.
    PARTY_CONTAINS = "PARTY_CONTAINS", "Counterparty contains"
    #: Anywhere in the normalised narration. The blunt instrument; use when the
    #: counterparty could not be extracted.
    NARRATION_CONTAINS = "NARRATION_CONTAINS", "Narration contains"
    #: Every transaction on a channel, e.g. all card repayments.
    CHANNEL_IS = "CHANNEL_IS", "Channel is"
    REGEX = "REGEX", "Narration matches regular expression"


class Direction(models.TextChoices):
    ANY = "ANY", "Either"
    DEBIT = "DEBIT", "Money out"
    CREDIT = "CREDIT", "Money in"


class RuleSource(models.TextChoices):
    #: Shipped with the system. Channel-level accounting that is true for
    #: everyone, e.g. interest the bank paid is income.
    SEED = "SEED", "Built in"
    #: Derived from a person's decision on a row they reviewed.
    LEARNED = "LEARNED", "Learned from a review"
    MANUAL = "MANUAL", "Written by hand"


class ClassificationRule(UUIDModel, FirmScopedModel):
    """One mapping from a narration pattern to a ledger."""

    #: NULL means the rule applies to every client in the firm. Scoping to a
    #: client is the default because payee meanings are not portable between
    #: them; see the module docstring.
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="classification_rules", null=True, blank=True
    )
    # -- the treatment this rule applies -----------------------------------
    # All four together, because they were decided together. A rule that
    # remembered the ledger and forgot the reverse-charge flag would look like
    # it worked until a return was prepared from incomplete books.
    ledger = models.ForeignKey(LedgerAccount, on_delete=models.CASCADE, related_name="rules")
    vendor = models.ForeignKey(
        Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name="rules"
    )
    rcm = models.BooleanField(default=False)
    tds_section = models.CharField(max_length=16, blank=True, choices=TdsSection.CHOICES)

    #: How sure a match on this rule should make us. Defaulted from the match
    #: type -- a rule learned from a person naming this exact payee is a far
    #: stronger claim than one matching every transaction on a channel -- and
    #: adjustable per rule, because a firm knows its own exceptions.
    confidence = models.FloatField(default=0.9)

    match_type = models.CharField(
        max_length=24, choices=MatchType.choices, default=MatchType.PARTY_EQUALS
    )
    #: Stored already normalised for the party and narration match types, so
    #: matching never has to normalise on the read path.
    pattern = models.CharField(max_length=255)
    direction = models.CharField(max_length=8, choices=Direction.choices, default=Direction.ANY)

    #: Higher wins. Client rules outrank firm rules, and both outrank seeds, by
    #: convention of the values assigned in ``classify.seeds``.
    priority = models.IntegerField(default=100)
    source = models.CharField(max_length=16, choices=RuleSource.choices, default=RuleSource.LEARNED)
    is_active = models.BooleanField(default=True)

    #: Maintained by the engine. A rule that never fires is either dead weight
    #: or a sign that the narration it was written for has changed shape.
    hit_count = models.PositiveIntegerField(default=0)
    last_hit_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="classification_rules"
    )

    class Meta:
        db_table = "classify_rule"
        ordering = ["-priority", "pattern"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "match_type", "pattern", "direction"],
                name="uniq_rule_per_client_pattern",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "client", "is_active"], name="idx_rule_client_active"),
        ]

    def __str__(self) -> str:
        return f"{self.get_match_type_display()} {self.pattern!r} -> {self.ledger_id}"

    @property
    def treatment(self) -> Treatment:
        return Treatment(
            ledger=self.ledger, vendor=self.vendor, rcm=self.rcm, tds_section=self.tds_section
        )

    def matches(self, facts, is_debit: bool) -> bool:
        """True if this rule claims a transaction with these narration facts."""
        if not self.is_active:
            return False
        if self.direction == Direction.DEBIT and not is_debit:
            return False
        if self.direction == Direction.CREDIT and is_debit:
            return False

        if self.match_type == MatchType.CHANNEL_IS:
            return facts.channel == self.pattern
        if self.match_type == MatchType.REGEX:
            return bool(re.search(self.pattern, facts.raw, re.IGNORECASE))

        from classify.narration import normalise

        if self.match_type == MatchType.PARTY_EQUALS:
            return bool(facts.counterparty) and normalise(facts.counterparty) == self.pattern
        if self.match_type == MatchType.PARTY_CONTAINS:
            return bool(facts.counterparty) and self.pattern in normalise(facts.counterparty)
        return self.pattern in normalise(facts.raw)


class ClassificationMethod(models.TextChoices):
    RULE = "RULE", "Matched a rule"
    #: No rule matched. The ledger is NULL and the row is queued for a person.
    UNRESOLVED = "UNRESOLVED", "Awaiting review"
    REVIEWED = "REVIEWED", "Set by a person"
    LLM = "LLM", "Suggested by a language model"


class TransactionClassification(UUIDModel, FirmScopedModel):
    """What one transaction was taken to mean, and on whose authority."""

    transaction = models.OneToOneField(
        StatementTransaction, on_delete=models.CASCADE, related_name="classification"
    )
    #: NULL while unresolved. A null ledger and ``needs_review`` are the same
    #: state said twice, which is deliberate: the queue is a cheap indexed
    #: boolean lookup, and "unclassified" stays visible in a join that drops
    #: nulls.
    ledger = models.ForeignKey(
        LedgerAccount, on_delete=models.PROTECT, related_name="classifications", null=True, blank=True
    )
    vendor = models.ForeignKey(
        Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name="classifications"
    )
    rcm = models.BooleanField(default=False)
    tds_section = models.CharField(max_length=16, blank=True, choices=TdsSection.CHOICES)

    method = models.CharField(
        max_length=16, choices=ClassificationMethod.choices, default=ClassificationMethod.UNRESOLVED
    )
    rule = models.ForeignKey(
        ClassificationRule,
        on_delete=models.SET_NULL,
        related_name="classifications",
        null=True,
        blank=True,
    )
    #: Design principle: every automated decision carries a confidence and a
    #: provenance. ``method`` and ``rule`` are the provenance; this is the
    #: confidence, and ``review_band`` is how it is presented.
    confidence = models.FloatField(default=0.0)
    review_band = models.CharField(
        max_length=12, choices=ReviewBand.CHOICES, default=ReviewBand.JUDGEMENT
    )
    needs_review = models.BooleanField(default=True)

    #: Facts read out of the narration at classification time, kept so the
    #: review screen can show why a row was placed where it was without
    #: re-deriving them against code that has since changed.
    channel = models.CharField(max_length=16, blank=True)
    counterparty = models.CharField(max_length=255, blank=True)
    is_self_transfer = models.BooleanField(default=False)

    #: A model-sourced suggestion's reasoning, one sentence, for the reviewer.
    #: Also set when the model looked and declined, so the reviewer knows.
    rationale = models.TextField(
        blank=True,
        default="",
        help_text="Why the model suggested what it did, in one sentence a reviewer can check.",
    )

    #: A transfer between two of the client's own accounts appears on both
    #: statements. The first side approved writes the Contra entry; the other
    #: side points here instead of writing it again. A plain id rather than a
    #: foreign key: journal entries can never be deleted, and the column is
    #: added to a populated, RLS-forced table without a validating scan.
    mirrored_entry_id = models.UUIDField(null=True, blank=True, db_index=True)

    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="classifications"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classify_transaction_classification"
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "transaction"], name="uniq_classification_per_transaction"
            ),
            # An unresolved row has no ledger, and a resolved one has no reason
            # to claim it is unresolved. Keeping the two in step in the database
            # means the review queue cannot drift from what is actually placed.
            models.CheckConstraint(
                condition=(
                    models.Q(method="UNRESOLVED", ledger__isnull=True)
                    | ~models.Q(method="UNRESOLVED") & models.Q(ledger__isnull=False)
                ),
                name="ck_unresolved_has_no_ledger",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "needs_review"], name="idx_classification_queue"),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_id} -> {self.ledger_id or 'unresolved'}"

    @property
    def treatment(self) -> Treatment | None:
        if self.ledger is None:
            return None
        return Treatment(
            ledger=self.ledger, vendor=self.vendor, rcm=self.rcm, tds_section=self.tds_section
        )

    def apply(self, treatment: Treatment, *, method, confidence: float, rule=None, user=None):
        """Record a decision about this row, however it was reached.

        One method for all four sources -- rule, model, person -- so a new
        source cannot accidentally set some of the fields and leave the rest at
        their defaults.
        """
        self.ledger = treatment.ledger
        self.vendor = treatment.vendor
        self.rcm = treatment.rcm
        self.tds_section = treatment.tds_section
        self.method = method
        self.rule = rule
        self.confidence = confidence
        self.review_band = band_for(confidence)
        self.needs_review = confidence < 1.0
        if user is not None:
            self.reviewed_by = user
        return self

    def resolve(self, treatment: Treatment, user=None, *, method=ClassificationMethod.REVIEWED):
        """Place this row on a person's authority. Confidence is total.

        The timestamp is set whether or not a user was supplied. A resolve is by
        definition a deliberate act, and "reviewed, by nobody recorded" is a
        more honest gap than "never reviewed" -- the latter would let a
        command-line correction masquerade as an untouched row.
        """
        self.apply(treatment, method=method, confidence=1.0, user=user)
        self.needs_review = False
        self.reviewed_at = timezone.now()
        self.save(
            update_fields=[
                "ledger",
                "vendor",
                "rcm",
                "tds_section",
                "method",
                "rule",
                "confidence",
                "review_band",
                "needs_review",
                "reviewed_by",
                "reviewed_at",
            ]
        )
        return self
