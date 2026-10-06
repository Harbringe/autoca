"""Bank accounts, statements, and the transaction rows read out of them.

Three things here are worth understanding before changing anything:

* **Rows are facts, not judgements.** Nothing in this app says what a
  transaction *means* -- no ledger, no party, no tax treatment. That lives in
  ``classify/`` and points back at these rows, so re-classifying never rewrites
  the bank's own record of what happened.
* **Money is a whole number of paise**, in fields named ``*_paise``. See
  ``core/money.py`` for why the unit is in the field name.
* **The account number is encrypted**, with a keyed fingerprint beside it so
  rows can still be found. Statements arrive naming an account; matching that
  name to a row is the one operation the ciphertext cannot serve, which is
  exactly what the blind index is for.

``dedupe_hash`` is what makes re-uploading an overlapping period safe. CA firms
do this constantly -- a client sends April-September in October and April-March
in April, and the six months in the middle must not double up.
"""

from __future__ import annotations

import hashlib

from django.db import models

from core.crypto import blind_index, decrypt_text_for_firm, encrypt_for_firm
from core.models import Client, FirmScopedModel, UUIDModel
from documents.models import Document

#: Encryption context domain. A ciphertext minted for a bank account will not
#: decrypt when handed to code expecting GST data, which turns a whole class of
#: "wrong blob, right firm" bugs into a hard error.
CRYPTO_PURPOSE = "banking.account"


class AccountKind(models.TextChoices):
    """What an account with a statement is.

    A loan is an account too: it has a ledger, rows and a running balance. It differs in two ways. Its balance is
    what the client OWES, so a debit raises it; and its ledger is a liability, not a bank account.
    """

    BANK = "BANK", "Bank account"
    LOAN = "LOAN", "Loan account"
    #: A credit card: what the client owes the card company. Like a loan, a debit raises the balance.
    CARD = "CARD", "Credit card"


class BankAccount(UUIDModel, FirmScopedModel):
    """A client's bank account (or loan account), and the Tally ledger it posts to."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="bank_accounts")
    kind = models.CharField(
        max_length=8, choices=AccountKind.choices, default=AccountKind.BANK, db_default=AccountKind.BANK
    )
    bank_code = models.CharField(max_length=16, help_text="Parser identifier, e.g. AXIS.")

    #: AES-256-GCM under the firm's data key, bound to the firm id as additional
    #: authenticated data. Never read directly -- use ``account_number``.
    account_number_enc = models.BinaryField()
    #: Keyed fingerprint of the account number, for lookup and uniqueness. Not
    #: reversible; see ``core.crypto.blind_index``.
    account_number_hash = models.CharField(max_length=64, db_index=True)
    #: For display: "Axis ••••7214" without decrypting anything.
    account_last4 = models.CharField(max_length=4, blank=True)

    #: The holder's name as the *bank* prints it, encrypted. Classification
    #: compares narration parties against this to spot transfers between the
    #: client's own accounts; comparing against the firm's label for the client
    #: misses them, because a client filed as "Arjun Nair" appears in their
    #: own NEFT narrations as "Arjun Pratap Nair".
    account_holder_enc = models.BinaryField(blank=True, null=True)

    ifsc = models.CharField(max_length=16, blank=True)

    #: The name of this account's ledger in the client's books. Posted entries
    #: find the ledger by this string, so renaming goes through
    #: ``classify.seeds.rename_account_ledger``, which moves the entries with it;
    #: a name changed any other way would leave the account pointing at an empty
    #: ledger.
    ledger_name = models.CharField(max_length=255, blank=True)

    #: Explicitly confirmed, never assumed to be zero. A client onboarding in
    #: October has nine months of history this system will never see, and
    #: starting their books at zero misstates every balance from then on.
    opening_balance_paise = models.BigIntegerField(null=True, blank=True)
    opening_as_of = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "banking_bank_account"
        ordering = ["bank_code", "account_last4"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "bank_code", "account_number_hash"],
                name="uniq_bank_account_per_client",
            ),
            # An opening balance without a date is meaningless, and a date
            # without a balance is a half-finished confirmation.
            models.CheckConstraint(
                condition=(
                    models.Q(opening_balance_paise__isnull=True, opening_as_of__isnull=True)
                    | models.Q(opening_balance_paise__isnull=False, opening_as_of__isnull=False)
                ),
                name="ck_opening_balance_has_a_date",
            ),
        ]

    def __str__(self) -> str:
        return self.ledger_name or f"{self.bank_code} ••••{self.account_last4}"

    # -- the encrypted pair, handled in one place -----------------------------

    @property
    def account_number(self) -> str:
        return decrypt_text_for_firm(bytes(self.account_number_enc), self.firm_id, CRYPTO_PURPOSE)

    @property
    def account_holder(self) -> str:
        if not self.account_holder_enc:
            return ""
        return decrypt_text_for_firm(bytes(self.account_holder_enc), self.firm_id, CRYPTO_PURPOSE)

    def set_account_number(self, number: str) -> None:
        """Set all three columns together. They must never disagree."""
        number = number.strip()
        self.account_number_enc = encrypt_for_firm(number, self.firm_id, CRYPTO_PURPOSE)
        self.account_number_hash = blind_index(number, self.firm_id, CRYPTO_PURPOSE)
        self.account_last4 = number[-4:]

    def set_account_holder(self, name: str) -> None:
        self.account_holder_enc = (
            encrypt_for_firm(name.strip(), self.firm_id, CRYPTO_PURPOSE) if name else None
        )

    @classmethod
    def lookup_hash(cls, number: str, firm_id) -> str:
        """The value to filter ``account_number_hash`` on."""
        return blind_index(number.strip(), firm_id, CRYPTO_PURPOSE)

    def save(self, *args, **kwargs):
        if not self.ledger_name:
            self.ledger_name = self.default_ledger_name()
        return super().save(*args, **kwargs)

    def default_ledger_name(self) -> str:
        """A bank ledger name that does not put the account number on every screen and export.

        The ledger name is plaintext everywhere it goes -- reports, the Day Book --
        so it carries the last four digits, a common convention. A
        client with two accounts at one bank ending in the same digits gets the
        full number instead, because two accounts sharing a ledger would merge
        their books. A CA can rename either, or a Tally import can.
        """
        label = {AccountKind.LOAN: "Loan A/c", AccountKind.CARD: "Credit Card A/c"}.get(self.kind, "Bank A/c")
        bank = f"{self.bank_code.title()} {label}"
        short = f"{bank} {self.account_last4}"
        clash = (
            BankAccount.objects.filter(client_id=self.client_id, ledger_name=short)
            .exclude(pk=self.pk)
            .exists()
        )
        return f"{bank} {self.account_number}" if clash else short

    @property
    def is_liability(self) -> bool:
        """What the account holds is owed by the client (a loan, a card): its balance rises with a debit."""
        return self.kind in (AccountKind.LOAN, AccountKind.CARD)

    @property
    def has_opening_balance(self) -> bool:
        return self.opening_balance_paise is not None


class Statement(UUIDModel, FirmScopedModel):
    """What was read out of one bank-statement document.

    The file itself is a :class:`~documents.models.Document`; this is the parse
    of it. Splitting them matters when a parser bug is fixed and re-run: the
    file is unchanged and keeps its identity, while everything derived from it
    is replaceable.

    The balances here are the *statement's own* figures, copied verbatim. They
    are what the rows were proved against at parse time, which makes that proof
    re-runnable later and makes the month-end check possible at all.
    """

    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="statement")
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="statements"
    )

    period_start = models.DateField()
    period_end = models.DateField()
    opening_balance_paise = models.BigIntegerField()
    closing_balance_paise = models.BigIntegerField()
    total_debit_paise = models.BigIntegerField()
    total_credit_paise = models.BigIntegerField()
    transaction_count = models.PositiveIntegerField(default=0)

    parser = models.CharField(max_length=64, blank=True)
    #: Bumped whenever a parser's output could change. A parser bug can then be
    #: re-run against exactly the statements it affected, rather than against
    #: everything or against a list someone kept by hand.
    parser_version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "banking_statement"
        ordering = ["-period_end", "-created_at"]
        indexes = [
            models.Index(
                fields=["firm", "bank_account", "period_start"], name="idx_stmt_account_period"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.bank_account} {self.period_start:%d-%m-%Y} to {self.period_end:%d-%m-%Y}"
        )


class StatementTransaction(UUIDModel, FirmScopedModel):
    """One row of one statement, exactly as the bank printed it."""

    statement = models.ForeignKey(
        Statement, on_delete=models.CASCADE, related_name="transactions"
    )
    #: Denormalised from ``statement``. Classification and the ledger query by
    #: account across statements, and this keeps that off a join on every read.
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="transactions"
    )

    row_number = models.PositiveIntegerField(help_text="1-based position within the statement.")
    value_date = models.DateField()
    narration = models.TextField(help_text="The bank's particulars, line wrapping removed.")
    cheque_number = models.CharField(max_length=32, blank=True)
    debit_paise = models.BigIntegerField(default=0)
    credit_paise = models.BigIntegerField(default=0)
    balance_paise = models.BigIntegerField()
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
            # The real idempotency boundary: one transaction never lands twice
            # for an account, even from two overlapping statement files.
            models.UniqueConstraint(
                fields=["firm", "bank_account", "dedupe_hash"],
                name="uniq_transaction_per_account",
            ),
            models.CheckConstraint(
                condition=models.Q(debit_paise__gte=0) & models.Q(credit_paise__gte=0),
                name="ck_transaction_amounts_non_negative",
            ),
            # Direction is carried by the column, so exactly one side is filled.
            # Both or neither means the parse went wrong upstream.
            models.CheckConstraint(
                condition=(
                    (models.Q(debit_paise__gt=0) & models.Q(credit_paise=0))
                    | (models.Q(debit_paise=0) & models.Q(credit_paise__gt=0))
                ),
                name="ck_transaction_is_one_sided",
            ),
        ]
        indexes = [
            models.Index(
                fields=["firm", "bank_account", "value_date"], name="idx_txn_account_date"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.value_date:%d-%m-%Y} {self.amount_paise} {'Dr' if self.is_debit else 'Cr'}"

    @property
    def is_debit(self) -> bool:
        return self.debit_paise > 0

    @property
    def amount_paise(self) -> int:
        return self.debit_paise if self.is_debit else self.credit_paise

    @property
    def signed_paise(self) -> int:
        """Effect on the balance: negative for money out."""
        return self.credit_paise - self.debit_paise

    @staticmethod
    def compute_dedupe_hash(
        *, account_hash: str, value_date, narration: str, debit_paise: int, credit_paise: int,
        balance_paise: int,
    ) -> str:
        """Identity of a transaction, independent of which file it arrived in.

        The running balance is part of it on purpose. Two payments of the same
        amount to the same payee on the same day are genuinely distinct rows,
        and the balance after each is the only thing on the statement that
        tells them apart.

        Keyed on the account's blind index rather than its number, so no
        plaintext account number is reconstructible from this column.
        """
        parts = [
            account_hash,
            value_date.isoformat(),
            " ".join(str(narration).split()).upper(),
            str(int(debit_paise)),
            str(int(credit_paise)),
            str(int(balance_paise)),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
