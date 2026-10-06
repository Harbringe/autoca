"""Employees and monthly salary runs."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr
from ledger.models import Employee, PayrollLine, PayrollRun


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "name", "is_active", "ledger"]
        read_only_fields = ["id", "ledger"]


class SalaryLineSerializer(serializers.Serializer):
    employee = serializers.UUIDField()
    gross_paise = PaiseField(min_value=1)
    pf_employee_paise = PaiseField(min_value=0, default=0)
    pf_employer_paise = PaiseField(min_value=0, default=0)
    esi_employee_paise = PaiseField(min_value=0, default=0)
    esi_employer_paise = PaiseField(min_value=0, default=0)
    tds_paise = PaiseField(min_value=0, default=0, help_text="Tax deducted on salary (section 192).")
    other_deduction_paise = PaiseField(min_value=0, default=0)


class PayrollRunCreateSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2017, max_value=2100)
    month = serializers.IntegerField(min_value=1, max_value=12)
    lines = SalaryLineSerializer(many=True, allow_empty=False, max_length=500)


class PayrollLineSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    net_display = serializers.SerializerMethodField()
    gross_display = serializers.SerializerMethodField()

    class Meta:
        model = PayrollLine
        fields = [
            "id", "employee", "employee_name", "gross_paise", "gross_display", "pf_employee_paise", "pf_employer_paise",
            "esi_employee_paise", "esi_employer_paise", "tds_paise", "other_deduction_paise", "net_paise", "net_display",
        ]
        read_only_fields = fields

    def get_net_display(self, obj) -> str:
        return format_inr(obj.net_paise)

    def get_gross_display(self, obj) -> str:
        return format_inr(obj.gross_paise)


class PayrollRunSerializer(serializers.ModelSerializer):
    gross_display = serializers.SerializerMethodField()
    net_display = serializers.SerializerMethodField()
    lines = PayrollLineSerializer(many=True, read_only=True)

    class Meta:
        model = PayrollRun
        fields = ["id", "year", "month", "entry", "gross_paise", "gross_display", "net_paise", "net_display", "lines"]
        read_only_fields = fields

    def get_gross_display(self, obj) -> str:
        return format_inr(obj.gross_paise)

    def get_net_display(self, obj) -> str:
        return format_inr(obj.net_paise)
