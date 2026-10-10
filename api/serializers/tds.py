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


class ReturnDeducteeSerializer(serializers.Serializer):
    date = serializers.DateField()
    party = serializers.CharField()
    pan = serializers.CharField(help_text="Blank when the party has no GSTIN on file to read it from.")
    section = serializers.CharField()
    paid_paise = PaiseField(help_text="The amount the deduction was made on (the bill's taxable value).")
    rate = serializers.FloatField()
    deducted_paise = PaiseField()
    voucher = serializers.CharField()


class ReturnChallanSerializer(serializers.Serializer):
    section = serializers.CharField()
    bsr_code = serializers.CharField()
    serial = serializers.CharField()
    paid_on = serializers.DateField()
    amount_paise = PaiseField()


class TdsReturnSerializer(serializers.Serializer):
    financial_year = serializers.IntegerField()
    quarter = serializers.IntegerField()
    due = serializers.DateField()
    deducted_paise = PaiseField()
    deposited_paise = PaiseField()
    interest_paise = PaiseField(help_text="Estimated interest on late or missing deposits.")
    fee_paise = PaiseField(help_text="Estimated section 234E fee if the return is past its due date.")
    warnings = serializers.ListField(child=serializers.CharField())
    deductees = ReturnDeducteeSerializer(many=True)
    challans = ReturnChallanSerializer(many=True)


def return_payload(pack) -> dict:
    return {
        "financial_year": pack.financial_year,
        "quarter": pack.quarter,
        "due": pack.due,
        "deducted_paise": pack.deducted_paise,
        "deposited_paise": pack.deposited_paise,
        "interest_paise": pack.interest_paise,
        "fee_paise": pack.fee_paise,
        "warnings": pack.warnings,
        "deductees": [
            {
                "date": d.date, "party": d.party, "pan": d.pan, "section": d.section, "paid_paise": d.paid_paise,
                "rate": d.rate, "deducted_paise": d.deducted_paise, "voucher": d.voucher,
            }
            for d in pack.deductees
        ],
        "challans": pack.challans,
    }


class SalaryRowSerializer(serializers.Serializer):
    employee = serializers.CharField()
    gross_paise = PaiseField()
    tds_paise = PaiseField()


class SalaryReturnSerializer(serializers.Serializer):
    financial_year = serializers.IntegerField()
    quarter = serializers.IntegerField()
    due = serializers.DateField()
    deducted_paise = PaiseField()
    deposited_paise = PaiseField()
    interest_paise = PaiseField()
    fee_paise = PaiseField()
    warnings = serializers.ListField(child=serializers.CharField())
    employees = SalaryRowSerializer(many=True)
    challans = ReturnChallanSerializer(many=True)


def salary_return_payload(pack) -> dict:
    return {
        "financial_year": pack.financial_year, "quarter": pack.quarter, "due": pack.due,
        "deducted_paise": pack.deducted_paise, "deposited_paise": pack.deposited_paise,
        "interest_paise": pack.interest_paise, "fee_paise": pack.fee_paise, "warnings": pack.warnings,
        "employees": [{"employee": r.employee, "gross_paise": r.gross_paise, "tds_paise": r.tds_paise} for r in pack.rows],
        "challans": pack.challans,
    }
