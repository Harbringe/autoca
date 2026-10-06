"""TDS: what was deducted and deposited, and the challans that say how."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr
from ledger.models import TdsChallan


class TdsMonthSerializer(serializers.Serializer):
    section = serializers.CharField(help_text="The TDS section, or `?` where a deduction carried none.")
    financial_year = serializers.IntegerField()
    quarter = serializers.IntegerField(help_text="1 is April to June.")
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    deducted_paise = PaiseField()
    deducted_display = serializers.CharField()
    deposited_paise = PaiseField(help_text="Matched to this month, oldest deduction first, from the challans recorded for the section.")
    deposited_display = serializers.CharField()
    unpaid_paise = PaiseField()
    unpaid_display = serializers.CharField()
    due = serializers.DateField()
    overdue = serializers.BooleanField()


class TdsPaymentSerializer(serializers.Serializer):
    entry = serializers.UUIDField()
    entry_date = serializers.DateField()
    amount_paise = PaiseField()
    amount_display = serializers.CharField()


class TdsSummarySerializer(serializers.Serializer):
    months = TdsMonthSerializer(many=True)
    payments_without_challan = TdsPaymentSerializer(many=True)


class ChallanCreateSerializer(serializers.Serializer):
    entry = serializers.UUIDField(help_text="The bank payment to the tax department (booked to TDS Payable).")
    section = serializers.CharField(max_length=16, help_text="The section the challan is for, like 194C.")
    bsr_code = serializers.CharField(max_length=7, help_text="The seven-digit BSR code of the bank branch.")
    serial = serializers.CharField(max_length=5, help_text="The five-digit challan serial number.")
    paid_on = serializers.DateField()


class ChallanSerializer(serializers.ModelSerializer):
    class Meta:
        model = TdsChallan
        fields = ["id", "entry", "section", "bsr_code", "serial", "paid_on"]
        read_only_fields = fields


def summary_payload(months, payments, today) -> dict:
    return {
        "months": [
            {
                "section": m.section,
                "financial_year": m.financial_year,
                "quarter": m.quarter,
                "year": m.year,
                "month": m.month,
                "deducted_paise": m.deducted_paise,
                "deducted_display": format_inr(m.deducted_paise),
                "deposited_paise": m.deposited_paise,
                "deposited_display": format_inr(m.deposited_paise),
                "unpaid_paise": m.unpaid_paise,
                "unpaid_display": format_inr(m.unpaid_paise),
                "due": m.due,
                "overdue": m.unpaid_paise > 0 and today > m.due,
            }
            for m in months
        ],
        "payments_without_challan": [
            {"entry": e.pk, "entry_date": e.entry_date, "amount_paise": a, "amount_display": format_inr(a)} for e, a in payments
        ],
    }
