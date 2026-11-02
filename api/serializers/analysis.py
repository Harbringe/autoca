"""Group summary and a ledger's month-by-month figures."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField


class GroupLedgerSerializer(serializers.Serializer):
    ledger_id = serializers.UUIDField(allow_null=True)
    name = serializers.CharField()
    opening_paise = PaiseField(help_text="Debits positive.")
    debit_paise = PaiseField()
    credit_paise = PaiseField()
    closing_paise = PaiseField(help_text="Debits positive.")


class GroupSerializer(serializers.Serializer):
    group = serializers.CharField()
    label = serializers.CharField()
    opening_paise = PaiseField()
    debit_paise = PaiseField()
    credit_paise = PaiseField()
    closing_paise = PaiseField()
    ledgers = GroupLedgerSerializer(many=True)


class GroupSummarySerializer(serializers.Serializer):
    fy = serializers.IntegerField()
    groups = GroupSerializer(many=True)
    total_debit_paise = PaiseField()
    total_credit_paise = PaiseField()


class LedgerMonthSerializer(serializers.Serializer):
    month = serializers.CharField(help_text="YYYY-MM")
    debit_paise = PaiseField()
    credit_paise = PaiseField()
    closing_paise = PaiseField(help_text="The balance after the month, debits positive.")


class LedgerInfoSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    group = serializers.CharField()
    group_label = serializers.CharField()


class LedgerMonthlySerializer(serializers.Serializer):
    fy = serializers.IntegerField()
    ledger = LedgerInfoSerializer()
    opening_paise = PaiseField()
    months = LedgerMonthSerializer(many=True)
    total_debit_paise = PaiseField()
    total_credit_paise = PaiseField()
    closing_paise = PaiseField()
