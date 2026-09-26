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
* A rule is scoped to one client, always, and cannot be promoted to the firm.
  Payee meanings are not universal -- one firm's ``ZERODHA`` is a broker's fee,
  the next firm's is the client's own investment -- and a rule shared across
  clients would quietly cross-contaminate their books. There is also nothing a
  shared rule could point at: a ledger belongs to one client, so a firm-wide
  rule would name one client's ledger and post everyone else's money into it.
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
#:
#: Still "vendor" though the model is now ``Party``. This string is mixed into
#: the key derivation and the blind index, so changing it would make every
#: GSTIN already stored undecryptable and every hash already indexed unfindable.
#: It is a storage detail, not a name anyone reads.
CRYPTO_PURPOSE = "classify.vendor"

#: Separate domain for counterparty account numbers, so that a party's account
#: and one of the client's own accounts never produce the same blind index.
#: They are different questions -- "who did we pay" and "which of our accounts
#: paid" -- and a collision between them would resolve a self-transfer to a
#: party.
PARTY_ACCOUNT_PURPOSE = "classify.party_bank"


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


class PartyRole(models.TextChoices):
    """Which side of the books a party sits on.

    A supplier and a customer are the same kind of object -- a name, a GSTIN, a
    balance -- differing only in which way the balance runs, so they share a
    table. ``BOTH`` is common enough to be worth naming: a firm that buys
    stationery from a client is not two parties. ``OTHER`` covers the ones that
    are neither, which is where a naive vendor/customer split breaks down --
    a lender, an employee, a partner drawing from capital.
    """

    VENDOR = "VENDOR", "Supplier"
    CUSTOMER = "CUSTOMER", "Customer"
    BOTH = "BOTH", "Both supplier and customer"
    OTHER = "OTHER", "Other (lender, employee, related party)"


class Party(UUIDModel, FirmScopedModel):
    """A party the client transacts with.

    Separate from the ledger head because they answer different questions. The
    ledger says what kind of expense it was; the party says who it was with,
    and "how much did we pay this party this year" is a question a firm is
    asked constantly and cannot answer from ledger heads alone.

    The party is also where reverse-charge and TDS defaults live, because those
    are properties of *who you are paying*, not of the category you booked it
    under. A goods transport agency is reverse-charge whether the payment lands
    in Freight or in Direct Expenses. Those two fields are meaningful only when
    the role includes ``VENDOR`` -- nobody deducts TDS from a customer -- and
    are left at their defaults otherwise.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="parties")
    canonical_name = models.CharField(max_length=255)
    role = models.CharField(max_length=16, choices=PartyRole.choices, default=PartyRole.VENDOR)

    #: A stable stand-in for the name -- "V" plus a short hash. When a narration
    #: is sent to a language model for classification, known parties are
    #: replaced by this, so the model sees the shape of the transaction without
    #: the counterparty's identity. The mapping back happens server-side.
    #:
    #: Not to be confused with ``PartyAlias``, which is the opposite concern:
    #: this hides a name from the model, that one recognises a name the bank
    #: spelled differently. They never interact.
    alias_token = models.CharField(max_length=24, db_index=True)

    gstin_enc = models.BinaryField(blank=True, null=True)
    gstin_hash = models.CharField(max_length=64, blank=True, db_index=True)

    #: Reverse charge applies to this party by default. Learned once per client
    #: and then applied, rather than re-decided every month.
    rcm_default = models.BooleanField(default=False)
    #: TDS section that normally applies to payments to this party, if any.
    tds_section = models.CharField(max_length=16, blank=True, choices=TdsSection.CHOICES)

    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "classify_party"
        ordering = ["canonical_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "canonical_name"], name="uniq_party_name_per_client"
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
        party GSTIN. That join has to work on ciphertext that is different
        every time, which is what the hash column is for.
        """
        gstin = (gstin or "").strip().upper()
        if not gstin:
            self.gstin_enc = None
            self.gstin_hash = ""
            return
        self.gstin_enc = encrypt_for_firm(gstin, self.firm_id, CRYPTO_PURPOSE)
        self.gstin_hash = blind_index(gstin, self.firm_id, CRYPTO_PURPOSE)


class AliasSource(models.TextChoices):
    """Where a spelling of a party's name was first seen."""

    BANK_NARRATION = "BANK_NARRATION", "From a bank narration"
    INVOICE = "INVOICE", "From an invoice"
    MANUAL = "MANUAL", "Entered by hand"


class PartyAlias(UUIDModel, FirmScopedModel):
    """One spelling of a party's name, confirmed by a person.

    A bank prints the same payee three ways -- ``RAMESH TRADRS PVT``,
    ``Ramesh Traders``, ``RAMESH TRADERS-SETTL`` -- and an exact match on the
    canonical name recognises none of them. Fuzzy matching can *suggest* that
    these are one party, but it may never decide: merging two people's ledgers
    on a string-similarity score is a mistake nobody would find until the books
    were wrong in both directions.

    So the alias table is the memory of decisions already made. A person
    confirms a spelling once; from then on it resolves exactly, with no
    similarity score involved. This is the same shape as
    ``classify.engine.learn_rule_from`` -- a human decision becomes a
    deterministic rule so it is never asked twice.

    The unique constraint is the point: within a client, one spelling resolves
    to exactly one party. Without it, resolution would be ambiguous exactly
    where it needs to be certain.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="party_aliases")
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="aliases")

    #: The form comparisons are made against -- see ``narration.normalise``.
    alias_normalised = models.CharField(max_length=255)
    #: As it was actually spelled, for showing a person what they confirmed.
    alias_display = models.CharField(max_length=255)

    source = models.CharField(
        max_length=16, choices=AliasSource.choices, default=AliasSource.BANK_NARRATION
    )
    confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="confirmed_aliases"
    )
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "classify_party_alias"
        ordering = ["alias_display"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "alias_normalised"], name="uniq_alias_per_client"
            ),
        ]
        indexes = [
            models.Index(
                fields=["firm", "client", "alias_normalised"], name="idx_alias_lookup"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.alias_display} -> {self.party_id}"


class PartyBankAccount(UUIDModel, FirmScopedModel):
    """An account number a party has been seen transacting from.

    The strongest identity signal there is, and the only one strong enough to
    resolve a party without asking anyone: two transfers quoting the same
    account number are the same counterparty, whatever the narration called
    them. Stored as a blind index rather than in the clear, for the same reason
    the client's own account numbers are -- see ``core.crypto``.

    Note the purpose string differs from the client's own accounts, so the two
    hash spaces never collide: a client paying themselves must not resolve to a
    party.
    """

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="party_bank_accounts"
    )
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="bank_accounts")

    account_hash = models.CharField(max_length=64, db_index=True)
    #: For showing a person which account this was, without storing the number.
    last4 = models.CharField(max_length=4, blank=True)
    ifsc = models.CharField(max_length=16, blank=True)

    source = models.CharField(
        max_length=16, choices=AliasSource.choices, default=AliasSource.BANK_NARRATION
    )
    confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="confirmed_accounts"
    )
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "classify_party_bank_account"
        ordering = ["last4"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "account_hash"], name="uniq_party_account_per_client"
            ),
        ]

    def __str__(self) -> str:
        return f"****{self.last4} -> {self.party_id}"

    @staticmethod
    def hash_for(account_number: str, firm_id) -> str:
        """The blind index this table is keyed on."""
        cleaned = re.sub(r"[^A-Z0-9]", "", (account_number or "").upper())
        if not cleaned:
            return ""
        return blind_index(cleaned, firm_id, PARTY_ACCOUNT_PURPOSE)


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

    #: Always a client. There is no firm-wide rule, and there cannot be one:
    #: every ``LedgerAccount`` belongs to exactly one client, so a rule that
    #: applied to the whole firm would still have to name one client's ledger
    #: and would post every other client's money into it. The generalisation
    #: has no ledger it could legally point at, so the column is NOT NULL.
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="classification_rules"
    )
    # -- the treatment this rule applies -----------------------------------
    # All four together, because they were decided together. A rule that
    # remembered the ledger and forgot the reverse-charge flag would look like
    # it worked until a return was prepared from incomplete books.
    ledger = models.ForeignKey(LedgerAccount, on_delete=models.CASCADE, related_name="rules")
    party = models.ForeignKey(
        Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="rules"
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

    #: Higher wins. A hand-written rule outranks a learned one, and both
    #: outrank the seeds, by convention of the values assigned in
    #: ``classify.seeds``. There is no firm tier: every rule is one client's.
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

    def clean(self):
        """A rule may only name things its own client owns.

        The database enforces this too, with a composite foreign key, and that
        is the guarantee that matters -- this method exists so the API returns
        a readable error instead of an IntegrityError. Keep the two in step: a
        check here that Postgres does not also make is a check that is one
        ``objects.create`` away from being skipped.
        """
        super().clean()
        errors = {}
        if self.client_id is None:
            errors["client"] = (
                "A rule belongs to one client. There are no firm-wide rules, because "
                "every ledger belongs to a client and a firm-wide rule would post "
                "other clients' transactions into it."
            )
        else:
            # These messages name no ledger, party or client. Staff are
            # assigned to particular clients, so an error that named the owner
            # would tell a reviewer who is not on that engagement that it
            # exists -- a smaller leak than the one being closed, but the same
            # kind. The offending id is in the request the caller sent.
            if self.ledger_id and self.ledger.client_id != self.client_id:
                errors["ledger"] = (
                    "That ledger belongs to another client. A rule cannot place "
                    "this client's transactions into it."
                )
            if self.party_id and self.party.client_id != self.client_id:
                errors["party"] = "That party belongs to another client."
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    @property
    def treatment(self) -> Treatment:
        return Treatment(
            ledger=self.ledger, party=self.party, rcm=self.rcm, tds_section=self.tds_section
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
    party = models.ForeignKey(
        Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="classifications"
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

    #: How sure the system is which party this counterparty is -- separate
    #: from whether the row's *ledger* is decided, because a firm can be
    #: certain "this is Ramesh Traders" while still needing a person to say
    #: which ledger the payment belongs in, and vice versa.
    #:
    #: Never set from a similarity score. See ``classify.parties``: the whole
    #: point of that module is that a fuzzy match is a ``Kind.CANDIDATE``,
    #: never a ``Kind.AUTO``, however high the score.
    party_resolution = models.CharField(
        max_length=16, blank=True, default="", choices=[
            ("AUTO", "Recognised from a fact -- an account number or GSTIN"),
            ("CANDIDATE", "Looks similar to a known party -- needs confirming"),
            ("NEW", "No known party looks like this"),
            ("CONFIRMED", "A person has confirmed which party this is"),
        ],
    )
    #: Suggestions for who this might be, when it is not certain -- name,
    #: score, and the reason, so a reviewer sees why rather than a bare guess.
    #: Never applied to ``party`` on its own; a person always confirms first.
    party_candidates = models.JSONField(default=list, blank=True)

    #: A model-sourced suggestion's reasoning, one sentence, for the reviewer.
    #: Also set when the model looked and declined, so the reviewer knows.
    rationale = models.TextField(
        blank=True,
        default="",
        help_text="Why the model suggested what it did, in one sentence a reviewer can check.",
    )

    #: The narration the entry will carry in the books, written the way a CA
    #: writes one -- "Being courier charges paid to ABC Courier vide UPI ref
    #: 7781" -- rather than the bank's own string. Set by the model when it
    #: books the row; a person may rewrite it at approval.
    book_narration = models.TextField(blank=True, default="")

    #: When the evidence does not say what a row is, the honest outcome is a
    #: question for the client, not a guess or a Suspense entry. One question,
    #: in plain words, that the answer to would settle the row.
    open_question = models.TextField(blank=True, default="")

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

    #: The AI moved this row after a person corrected a similar one. A finding
    #: aid only: it makes the row easy to spot among the rest, and is cleared as
    #: soon as a person looks and decides.
    ai_revised = models.BooleanField(default=False)

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
            ledger=self.ledger, party=self.party, rcm=self.rcm, tds_section=self.tds_section
        )

    def apply(self, treatment: Treatment, *, method, confidence: float, rule=None, user=None):
        """Record a decision about this row, however it was reached.

        One method for all four sources -- rule, model, person -- so a new
        source cannot accidentally set some of the fields and leave the rest at
        their defaults.
        """
        self.ledger = treatment.ledger
        self.party = treatment.party
        self.rcm = treatment.rcm
        self.tds_section = treatment.tds_section
        self.method = method
        self.rule = rule
        self.confidence = confidence
        self.review_band = band_for(confidence)
        self.needs_review = confidence < 1.0
        if method != ClassificationMethod.LLM:
            # A narration the model wrote describes the ledger the model chose. Once a rule or a
            # person has decided differently it would describe an entry that no longer exists
            # ("cash withdrawn" on a transfer between banks), so the plain one is used instead.
            self.book_narration = ""
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
        self.ai_revised = False
        self.reviewed_at = timezone.now()
        self.save(
            update_fields=[
                "ai_revised",
                "book_narration",
                "ledger",
                "party",
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
