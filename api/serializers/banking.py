"""Documents, accounts, statements and the rows read out of them.

Note what is *not* here: the account number. It is encrypted at rest and there
is no reason an API response should decrypt it -- ``account_last4`` identifies
an account to a person perfectly well, and a list screen showing thirty accounts
should not cost thirty decryptions. The full number is available on the detail
endpoint, to a caller who asked for exactly that one account.
"""

from __future__ import annotations

from rest_framework import serializers

from api.fields import MoneySerializerMixin, PaiseField
from banking.models import BankAccount, Statement, StatementTransaction
from documents.models import Document


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "kind",
            "original_filename",
            "sha256",
            "byte_size",
            "page_count",
            "pipeline_tier",
            "status",
            "failure_reason",
            "created_at",
        ]
        read_only_fields = fields


class BankAccountSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = ("opening_balance_paise",)

    label = serializers.CharField(source="__str__", read_only=True)
    has_opening_balance = serializers.BooleanField(read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "label",
            "client",
            "bank_code",
            "account_last4",
            "ifsc",
            "ledger_name",
            "opening_balance_paise",
            "opening_as_of",
            "has_opening_balance",
            "is_active",
            "created_at",
        ]
        read_only_fields = [f for f in fields if f != "ledger_name"]


class BankAccountDetailSerializer(BankAccountSerializer):
    """As above, plus the decrypted identifiers. One account at a time."""

    account_number = serializers.CharField(read_only=True)
    account_holder = serializers.CharField(read_only=True)

    class Meta(BankAccountSerializer.Meta):
        fields = [*BankAccountSerializer.Meta.fields, "account_number", "account_holder"]


class OpeningBalanceSerializer(serializers.Serializer):
    """Confirming what the client's books actually started from.

    Deliberately an explicit act rather than something inferred. A client
    onboarding in October has six months of history this system never saw, and
    starting them at the October statement's opening line misstates every
    balance from then on.
    """

    opening_balance_paise = PaiseField()
    opening_as_of = serializers.DateField(
        help_text="The date that balance was true. Normally the first day of the period."
    )


class StatementSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = (
        "opening_balance_paise",
        "closing_balance_paise",
        "total_debit_paise",
        "total_credit_paise",
    )

    document = DocumentSerializer(read_only=True)
    bank_account_label = serializers.CharField(source="bank_account.__str__", read_only=True)

    class Meta:
        model = Statement
        fields = [
            "id",
            "bank_account",
            "bank_account_label",
            "document",
            "period_start",
            "period_end",
            "opening_balance_paise",
            "closing_balance_paise",
            "total_debit_paise",
            "total_credit_paise",
            "transaction_count",
            "parser",
            "parser_version",
            "created_at",
        ]
        read_only_fields = fields


class StatementTransactionSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = ("debit_paise", "credit_paise", "balance_paise", "amount_paise")

    is_debit = serializers.BooleanField(read_only=True)
    amount_paise = PaiseField(read_only=True)

    class Meta:
        model = StatementTransaction
        fields = [
            "id",
            "statement",
            "bank_account",
            "row_number",
            "value_date",
            "narration",
            "cheque_number",
            "branch_code",
            "debit_paise",
            "credit_paise",
            "balance_paise",
            "amount_paise",
            "is_debit",
        ]
        read_only_fields = fields


class StatementUploadSerializer(serializers.Serializer):
    """A statement PDF, for a client.

    The bank is not asked for and cannot be supplied. It is read from the file:
    a dropdown is one more way to file a statement against the wrong account,
    and the statement itself is the authority on which account it belongs to.
    """

    file = serializers.FileField(help_text="The statement PDF, as uploaded by the client.")
    allow_gap = serializers.BooleanField(
        default=False,
        help_text=(
            "Accept a statement that does not continue from the last one on file. "
            "A gap means a missing period, so this defaults to refusing; set it "
            "only when the earlier period genuinely is not available."
        ),
    )
