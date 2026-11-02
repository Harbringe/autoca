"""Group summary and a ledger's month-by-month figures."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from ledger.models import CostCentre


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


class CostCentreSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostCentre
        fields = ["id", "name"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Name the cost centre.")
        return name

    def validate(self, attrs):
        client = self.context["view"].client
        name = attrs.get("name")
        if name is not None:
            clash = CostCentre.objects.filter(firm_id=client.firm_id, client=client, name__iexact=name).exclude(pk=getattr(self.instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError({"name": "This client already has a cost centre with that name."})
        return attrs


class TagAllocationSerializer(serializers.Serializer):
    cost_centre = serializers.UUIDField()
    amount_paise = PaiseField(min_value=1)


class CostCentreTagsSerializer(serializers.Serializer):
    """The cost centres one journal line is split across. Replaces what the line had; an empty list clears it."""

    line = serializers.UUIDField()
    allocations = TagAllocationSerializer(many=True, max_length=50)


class TagRowSerializer(serializers.Serializer):
    line = serializers.UUIDField()
    cost_centre = serializers.UUIDField()
    cost_centre_name = serializers.CharField()
    amount_paise = PaiseField()


class BudgetMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    amount_paise = PaiseField(allow_null=True)


class BudgetSerializer(serializers.Serializer):
    ledger_id = serializers.UUIDField()
    ledger = serializers.CharField()
    group = serializers.CharField()
    months = BudgetMonthSerializer(many=True)
    total_paise = PaiseField()


class BudgetSetSerializer(serializers.Serializer):
    """One ledger's budget for a year: an amount for each month named; a month set to null is cleared, a month left out is kept."""

    fy = serializers.IntegerField(min_value=2000, max_value=2100)
    ledger = serializers.UUIDField()
    months = serializers.DictField(child=PaiseField(min_value=0, allow_null=True), help_text="By month, YYYY-MM, e.g. '2025-04'.")


class VarianceMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    budget_paise = PaiseField(allow_null=True)
    actual_paise = PaiseField()
    variance_paise = PaiseField()


class VarianceLedgerSerializer(serializers.Serializer):
    ledger_id = serializers.UUIDField()
    ledger = serializers.CharField()
    is_income = serializers.BooleanField()
    months = VarianceMonthSerializer(many=True)
    budget_paise = PaiseField()
    actual_paise = PaiseField()
    variance_paise = PaiseField()


class BudgetVarianceSerializer(serializers.Serializer):
    fy = serializers.IntegerField()
    through = serializers.CharField(allow_null=True)
    ledgers = VarianceLedgerSerializer(many=True)


class CentreLedgerSerializer(serializers.Serializer):
    ledger = serializers.CharField()
    is_income = serializers.BooleanField()
    amount_paise = PaiseField()


class CentreReportRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    income_paise = PaiseField()
    expense_paise = PaiseField()
    net_paise = PaiseField()
    ledgers = CentreLedgerSerializer(many=True)


class CostCentreReportSerializer(serializers.Serializer):
    fy = serializers.IntegerField()
    centres = CentreReportRowSerializer(many=True)
    unallocated_income_paise = PaiseField()
    unallocated_expense_paise = PaiseField()
