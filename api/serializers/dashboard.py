"""The reporting dashboards: a client's position and trend, and the firm's portfolio."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import MoneySerializerMixin, PaiseField
from api.serializers.overview import (
    OverviewByStageSerializer,
    OverviewClientSerializer,
    OverviewTotalsSerializer,
)


class TrendMonthSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("income_paise", "expense_paise", "profit_paise")

    month = serializers.CharField(help_text="YYYY-MM.")
    income_paise = PaiseField()
    expense_paise = PaiseField()
    profit_paise = PaiseField()


class TopExpenseSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("amount_paise",)

    ledger = serializers.CharField()
    amount_paise = PaiseField()


class AccountBalanceSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("balance_paise",)

    label = serializers.CharField()
    kind = serializers.CharField()
    balance_paise = PaiseField(
        help_text="As the books hold it. For a card or loan, the amount owed."
    )


class TopPartySerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("amount_paise",)

    name = serializers.CharField()
    amount_paise = PaiseField()


class OwedSideSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("total_paise", "over_90_paise")

    total_paise = PaiseField()
    over_90_paise = PaiseField(help_text="Of the bills, how much is more than 90 days old.")
    top = TopPartySerializer(many=True)


class OwedSerializer(serializers.Serializer):
    receivables = OwedSideSerializer()
    payables = OwedSideSerializer()


class SnapshotBooksSerializer(serializers.Serializer):
    approved_through = serializers.DateField(allow_null=True)
    signed_off_through = serializers.DateField(
        allow_null=True, help_text="Sealed through this date."
    )
    changed_since_approval = serializers.IntegerField()
    close_period = serializers.CharField()
    next_seal_date = serializers.DateField(allow_null=True)


class SnapshotAttentionSerializer(serializers.Serializer):
    open_items = serializers.IntegerField()
    blocking_unexplained = serializers.IntegerField()
    failing_controls = serializers.ListField(child=serializers.CharField())


class ClientSnapshotSerializer(MoneySerializerMixin, serializers.Serializer):
    money = (
        "income_paise",
        "expense_paise",
        "profit_paise",
        "gst_net_payable_paise",
        "tds_payable_paise",
    )

    financial_year = serializers.IntegerField(help_text="The year the financial year starts in.")
    as_of = serializers.DateField()
    income_paise = PaiseField()
    expense_paise = PaiseField()
    profit_paise = PaiseField()
    trend = TrendMonthSerializer(many=True)
    top_expenses = TopExpenseSerializer(many=True)
    accounts = AccountBalanceSerializer(many=True)
    owed = OwedSerializer()
    gst_net_payable_paise = PaiseField(
        help_text="GST collected less input credit, in the books. Negative: a credit is carried."
    )
    tds_payable_paise = PaiseField(help_text="TDS deducted and not yet deposited, in the books.")
    books = SnapshotBooksSerializer()
    attention = SnapshotAttentionSerializer()


class PortfolioClientSerializer(MoneySerializerMixin, OverviewClientSerializer):
    money = ("tds_overdue_paise", "receivables_paise", "payables_paise")

    detail = serializers.BooleanField(
        help_text="False for a very large firm, where only the stage and next step are worked out."
    )
    approved_through = serializers.DateField(allow_null=True, required=False)
    changed_since_approval = serializers.IntegerField(required=False)
    seal_due = serializers.DateField(
        allow_null=True,
        required=False,
        help_text="The latest sealing date that has passed unsealed.",
    )
    next_seal_date = serializers.DateField(allow_null=True, required=False)
    open_items = serializers.IntegerField(required=False)
    blocking_unexplained = serializers.IntegerField(required=False)
    failing_controls = serializers.IntegerField(required=False)
    tds_overdue_paise = PaiseField(required=False)
    receivables_paise = PaiseField(required=False)
    payables_paise = PaiseField(required=False)


class AttentionItemSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("amount_paise",)

    severity = serializers.ChoiceField(choices=["critical", "high", "medium"])
    kind = serializers.CharField()
    client = serializers.UUIDField()
    client_name = serializers.CharField()
    text = serializers.CharField()
    amount_paise = PaiseField(allow_null=True)
    to = serializers.CharField(help_text="The screen where this is fixed, as an app path.")
    search = serializers.DictField(
        child=serializers.CharField(), help_text="The query that screen needs."
    )


class DeadlineSerializer(serializers.Serializer):
    date = serializers.DateField()
    label = serializers.CharField()
    clients = serializers.ListField(child=serializers.CharField())


class PortfolioSerializer(serializers.Serializer):
    totals = OverviewTotalsSerializer()
    by_stage = OverviewByStageSerializer()
    clients = PortfolioClientSerializer(many=True)
    attention = AttentionItemSerializer(many=True)
    deadlines = DeadlineSerializer(many=True)
    detailed = serializers.BooleanField()


class AlertSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("amount_paise",)

    kind = serializers.CharField()
    severity = serializers.ChoiceField(choices=["critical", "high", "medium"])
    module = serializers.ChoiceField(choices=["bank", "bookkeeping", "reports", "gst", "documents"])
    client = serializers.UUIDField(source="client_id")
    client_name = serializers.CharField()
    title = serializers.CharField(help_text="A few words: what is wrong.")
    detail = serializers.CharField(help_text="A sentence: what, how much, since when.")
    to = serializers.CharField(help_text="The screen where this is fixed, as an app path.")
    search = serializers.DictField(
        child=serializers.CharField(), help_text="The query that screen needs."
    )
    amount_paise = PaiseField(allow_null=True)
    count = serializers.IntegerField(help_text="How many rows, entries or items this stands for.")


class AlertCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    by_module = serializers.DictField(child=serializers.IntegerField())
    by_severity = serializers.DictField(child=serializers.IntegerField())


class AlertFeedSerializer(serializers.Serializer):
    counts = AlertCountsSerializer()
    alerts = AlertSerializer(many=True)
