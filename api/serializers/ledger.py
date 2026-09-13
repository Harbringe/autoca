"""Journal entries, corrections, reports and the month-end check.

Everything here is read-only over HTTP except the correction endpoint. Journal
entries are not created through a serializer -- they are created by approval,
which is a domain operation with a permission check and a voucher number to
allocate, not a POST to a collection.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.fields import MoneySerializerMixin, PaiseField
from api.serializers.classify import TreatmentSerializer
from ledger.models import JournalEntry, JournalLine


class JournalLineSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = ("amount_paise",)

    ledger_name = serializers.CharField(source="ledger_account.name", read_only=True)
    vendor_name = serializers.CharField(
        source="vendor.canonical_name", read_only=True, allow_null=True
    )

    class Meta:
        model = JournalLine
        fields = [
            "id",
            "ledger_account",
            "ledger_name",
            "vendor",
            "vendor_name",
            "direction",
            "amount_paise",
            "rcm",
            "tds_section",
        ]
        read_only_fields = fields


class JournalEntrySerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = ("total_paise",)

    lines = JournalLineSerializer(many=True, read_only=True)
    total_paise = PaiseField(read_only=True)
    fy_label = serializers.CharField(read_only=True)
    is_superseded = serializers.BooleanField(read_only=True)
    superseded_by = serializers.SerializerMethodField()
    approved_by_email = serializers.CharField(
        source="approved_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "entry_no",
            "voucher_type",
            "entry_date",
            "financial_year",
            "fy_label",
            "narration",
            "total_paise",
            "lines",
            "source_transaction",
            "supersedes",
            "superseded_by",
            "is_superseded",
            "approved_by",
            "approved_by_email",
            "approved_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_superseded_by(self, obj):
        """The entry that corrects this one, if any. A query, not a column --
        writing a ``superseded_by`` field would mean updating an append-only row."""
        entry = obj.superseded_by
        return entry.pk if entry else None


class CorrectionSerializer(serializers.Serializer):
    """Correct a posted entry.

    The original is not edited -- it cannot be. A correction is a new entry
    carrying a reversal of the original's lines plus the corrected ones, linked
    back to it. The original stays visible, which is what company law expects.
    """

    treatment = TreatmentSerializer()
    narration = serializers.CharField(
        required=False, allow_blank=True, help_text="Defaults to the original entry's narration."
    )


class LedgerBalanceSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("opening_paise", "debit_paise", "credit_paise", "closing_debit_paise", "closing_credit_paise")

    name = serializers.CharField()
    group = serializers.CharField()
    opening_paise = PaiseField(help_text="Balance before the year. Debits positive.")
    debit_paise = PaiseField()
    credit_paise = PaiseField()
    closing_debit_paise = PaiseField()
    closing_credit_paise = PaiseField()


class ReportFooterSerializer(serializers.Serializer):
    """What a reader needs in order to trust, or distrust, the figures above.

    ``is_complete`` is false whenever anything is still unposted, and the
    caption says so in words. A report over incomplete books is not wrong, but
    handing one to a client without knowing that is.
    """

    client_name = serializers.CharField()
    financial_year = serializers.IntegerField()
    fy_label = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    entry_count = serializers.IntegerField()
    pending_review = serializers.IntegerField()
    is_complete = serializers.BooleanField()
    generated_at = serializers.DateTimeField()
    # A method on the dataclass, not an attribute -- a plain CharField would
    # serialise the bound method's repr.
    caption = serializers.SerializerMethodField()

    def get_caption(self, footer) -> str:
        return footer.caption()


class TrialBalanceSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("total_debit_paise", "total_credit_paise")

    rows = LedgerBalanceSerializer(many=True)
    total_debit_paise = PaiseField()
    total_credit_paise = PaiseField()
    balances = serializers.BooleanField(
        help_text="False means something reached the books without going through a voucher."
    )
    footer = ReportFooterSerializer()


class ProfitAndLossSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("total_income_paise", "total_expenses_paise", "net_profit_paise")

    income = LedgerBalanceSerializer(many=True)
    expenses = LedgerBalanceSerializer(many=True)
    total_income_paise = PaiseField()
    total_expenses_paise = PaiseField()
    net_profit_paise = PaiseField(help_text="Positive is a profit, negative a loss.")
    footer = ReportFooterSerializer()


class BalanceSheetSerializer(MoneySerializerMixin, serializers.Serializer):
    money = (
        "total_assets_paise",
        "total_liabilities_paise",
        "total_liabilities_and_profit_paise",
        "net_profit_paise",
        "suspense_paise",
    )

    assets = LedgerBalanceSerializer(many=True)
    liabilities = LedgerBalanceSerializer(many=True)
    total_assets_paise = PaiseField()
    total_liabilities_paise = PaiseField()
    total_liabilities_and_profit_paise = PaiseField(
        help_text="Liabilities plus the year's profit (or minus its loss). Equals total assets when the sheet balances."
    )
    net_profit_paise = PaiseField()
    suspense_paise = PaiseField(
        help_text="Anything unanswered. A balance sheet with a suspense figure has a question on it."
    )
    balances = serializers.BooleanField()
    footer = ReportFooterSerializer()


class BalanceCheckSerializer(MoneySerializerMixin, serializers.Serializer):
    """Month end: does the ledger agree with the bank?

    The check that catches what every other one misses -- a row posted twice, a
    correction reversed the wrong way, an entry approved against the wrong
    account -- in one subtraction.
    """

    money = ("ledger_balance_paise", "statement_balance_paise", "difference_paise")

    as_of = serializers.DateField()
    ledger_balance_paise = PaiseField(help_text="What the client's books say.")
    statement_balance_paise = PaiseField(help_text="What the bank's own statement says.")
    difference_paise = PaiseField()
    matches = serializers.BooleanField()
    can_close = serializers.BooleanField(
        help_text="Reconciles *and* nothing up to that date is still unposted."
    )
    unapproved_count = serializers.IntegerField()
    explanation = serializers.SerializerMethodField()

    def get_explanation(self, check) -> str:
        return check.explain()


class TallyExportSerializer(serializers.Serializer):
    """A Tally Prime import document, and what was left out of it.

    ``unapproved`` is not an error. A firm exporting nine tenths of a statement
    while three rows wait on a client's answer is a normal Tuesday -- but an
    export that quietly included them would not be.
    """

    xml = serializers.CharField()
    voucher_count = serializers.IntegerField()
    ledger_count = serializers.IntegerField()
    unapproved = serializers.IntegerField(
        help_text="Rows classified but not approved, and therefore not exported."
    )
