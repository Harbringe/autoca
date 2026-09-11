"""Bank accounts, statements, and the transaction rows read out of them.

These are the first firm-scoped tables outside ``core``. Each one subclasses
:class:`~core.models.FirmScopedModel` and gets an RLS policy in the migration
that creates it; the isolation suite discovers them automatically and fails the
build if either half is missing.

Design notes worth keeping in mind when extending this:

* Rows are **facts**, not judgements. Nothing here says what a transaction
  *means* -- no ledger, no category, no party. That lives in ``classify/`` and
  points back at these rows, so a re-classification never rewrites the bank's
  own record of what happened.
* ``dedupe_hash`` makes re-uploading an overlapping period safe. CA firms do
  this constantly: a client sends April-September in October and April-March in
  April, and the six months in the middle must not double up. The hash includes
  the running balance, which is what distinguishes two genuinely separate
  transactions that happen to share a date, narration and amount.
* Money is ``Decimal``, never float. A statement that ties out to the paisa in
  Decimal will not in binary floating point, and the balance chain check in
  ``banking/parsers/base.py`` would start failing on correct parses.
"""

from __future__ import annotations

import hashlib

from django.db import models

from core.models import Client, FirmScopedModel, UUIDModel

#: 18 digits is comfortably past any Indian client's turnover, and two decimal
#: places is the paisa. Both are fixed here so no table drifts.
MONEY = {"max_digits": 18, "decimal_places": 2}


class BankAccount(UUIDModel, FirmScopedModel):
    """A client's bank account, and the Tally ledger it posts to."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="bank_accounts")
    bank_code = models.CharField(max_length=16, help_text="Parser identifier, e.g. AXIS.")
    account_number = models.CharField(max_length=32)
    ifsc = models.CharField(max_length=16, blank=True)

    #: The name as the *bank* prints it, which is rarely the name the firm filed
    #: the client under. Classification compares narration parties against this
    #: to spot transfers between the client's own accounts, and comparing
    #: against the firm's label instead misses them: a client filed as "Ramesh
    #: Deshmukh" appears in their own NEFT narrations as "Ramesh Gopal
    #: Deshmukh", and those are a contra entry, not income.
    account_holder = models.CharField(max_length=255, blank=True)

    #: The ledger name in the client's Tally company. Exported vouchers name
    #: this string, so it must match Tally exactly -- a near-miss creates a
    #: second ledger on import rather than failing.
    ledger_name = models.CharField(max_length=255, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "banking_bank_account"
        ordering = ["bank_code", "account_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "bank_code", "account_number"],
                name="uniq_bank_account_per_client",
            ),
        ]

    def __str__(self) -> str:
        return self.ledger_name or f"{self.bank_code} A/c {self.account_number}"

    def save(self, *args, **kwargs):
        if not self.ledger_name:
            self.ledger_name = self.default_ledger_name()
        return super().save(*args, **kwargs)

    def default_ledger_name(self) -> str:
        """Tally's own convention for a bank ledger, matched by the sample data."""
        return f"{self.bank_code.title()} Bank A/c {self.account_number}"


class Statement(UUIDModel, FirmScopedModel):
    """One parsed statement file.

    The balances and totals here are the *statement's own* figures, copied
    verbatim. They are what the transaction rows were proved against at parse
    time, and keeping them makes that proof re-runnable later against rows that
    may since have been edited.
    """

    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="statements"
    )

    source_filename = models.CharField(max_length=255, blank=True)
    #: SHA-256 of the uploaded bytes. The idempotency key: the same file
    #: uploaded twice is the same statement, whatever it was named.
    source_sha256 = models.CharField(max_length=64, db_index=True)
    storage_key = models.CharField(max_length=512, blank=True)

    period_start = models.DateField()
    period_end = models.DateField()
    opening_balance = models.DecimalField(**MONEY)
    closing_balance = models.DecimalField(**MONEY)
    total_debit = models.DecimalField(**MONEY)
    total_credit = models.DecimalField(**MONEY)
    transaction_count = models.PositiveIntegerField(default=0)

    parser = models.CharField(max_length=64, blank=True)
    page_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "banking_statement"
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "bank_account", "source_sha256"],
                name="uniq_statement_per_source_file",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "bank_account", "period_start"], name="idx_stmt_account_period"),
        ]

    def __str__(self) -> str:
        return f"{self.bank_account} {self.period_start:%d-%m-%Y} to {self.period_end:%d-%m-%Y}"


class StatementTransaction(UUIDModel, FirmScopedModel):
    """One row of one statement, exactly as the bank printed it."""

    statement = models.ForeignKey(
        Statement, on_delete=models.CASCADE, related_name="transactions"
    )
    #: Denormalised from ``statement``. Classification and ledger export query
    #: by account across statements, and this keeps that off a join that would
    #: otherwise be on every read path.
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="transactions"
    )

    row_number = models.PositiveIntegerField(help_text="1-based position within the statement.")
    value_date = models.DateField()
    narration = models.TextField(help_text="The bank's particulars, line wrapping removed.")
    cheque_number = models.CharField(max_length=32, blank=True)
    debit = models.DecimalField(default=0, **MONEY)
    credit = models.DecimalField(default=0, **MONEY)
    balance = models.DecimalField(**MONEY)
    branch_code = models.CharField(max_length=16, blank=True)

    dedupe_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "banking_statement_transaction"
        ordering = ["value_date", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "statement", "row_number"],
                name="uniq_transaction_row_per_statement",
            ),
            # The real idempotency boundary: the same transaction never lands
            # twice for an account, even from two overlapping statement files.
            models.UniqueConstraint(
                fields=["firm", "bank_account", "dedupe_hash"],
                name="uniq_transaction_per_account",
            ),
            models.CheckConstraint(
                condition=models.Q(debit__gte=0) & models.Q(credit__gte=0),
                name="ck_transaction_amounts_non_negative",
            ),
            # Direction is carried by the column, so exactly one side is filled.
            # A row with both or neither means the parse went wrong upstream.
            models.CheckConstraint(
                condition=(
                    (models.Q(debit__gt=0) & models.Q(credit=0))
                    | (models.Q(debit=0) & models.Q(credit__gt=0))
                ),
                name="ck_transaction_is_one_sided",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "bank_account", "value_date"], name="idx_txn_account_date"),
        ]

    def __str__(self) -> str:
        side = "Dr" if self.is_debit else "Cr"
        return f"{self.value_date:%d-%m-%Y} {self.amount} {side}"

    @property
    def is_debit(self) -> bool:
        return self.debit > 0

    @property
    def amount(self):
        return self.debit if self.is_debit else self.credit

    @staticmethod
    def compute_dedupe_hash(*, account_number, value_date, narration, debit, credit, balance) -> str:
        """Identity of a transaction, independent of which file it arrived in.

        The balance is part of it on purpose. Two payments of the same amount to
        the same payee on the same day are genuinely distinct rows, and the only
        thing on the statement that distinguishes them is the running balance
        after each.
        """
        parts = [
            str(account_number),
            value_date.isoformat(),
            " ".join(str(narration).split()).upper(),
            f"{debit:.2f}",
            f"{credit:.2f}",
            f"{balance:.2f}",
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
