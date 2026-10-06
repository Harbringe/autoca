"""The asset register: assets, what each has been depreciated by, and the schedule for a year."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr
from ledger.models import AssetMethod


class AssetCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    ledger = serializers.UUIDField(help_text="A ledger under Fixed Assets.")
    bill = serializers.UUIDField(
        required=False, allow_null=True, default=None, help_text="The purchase it was bought on. The cost cannot exceed what that purchase put on the ledger."
    )
    cost_paise = PaiseField(min_value=1)
    residual_paise = PaiseField(min_value=0, default=0, help_text="What it is worth at the end of its life.")
    put_to_use = serializers.DateField()
    method = serializers.ChoiceField(choices=AssetMethod.choices)
    life_years = serializers.IntegerField(min_value=0, max_value=100, default=0, help_text="Straight line only.")
    rate_bp = serializers.IntegerField(min_value=0, max_value=10000, default=0, help_text="Written-down value only: 1500 is 15%.")


class DisposeSerializer(serializers.Serializer):
    disposed_on = serializers.DateField()
    proceeds_paise = PaiseField(min_value=0, default=0, help_text="What it was sold for.")


class AssetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    ledger = serializers.UUIDField()
    ledger_name = serializers.CharField()
    bill = serializers.UUIDField(allow_null=True)
    cost_paise = PaiseField()
    cost_display = serializers.CharField()
    residual_paise = PaiseField()
    put_to_use = serializers.DateField()
    method = serializers.CharField()
    method_display = serializers.CharField()
    life_years = serializers.IntegerField()
    rate_bp = serializers.IntegerField()
    disposed_on = serializers.DateField(allow_null=True)
    disposal_paise = PaiseField(allow_null=True)


class ScheduleRowSerializer(serializers.Serializer):
    asset = AssetSerializer()
    days_in_use = serializers.IntegerField()
    opening_paise = PaiseField()
    opening_display = serializers.CharField()
    depreciation_paise = PaiseField(help_text="Charged for the year. Computed from the terms, never stored.")
    depreciation_display = serializers.CharField()
    closing_paise = PaiseField()
    closing_display = serializers.CharField()
    accumulated_paise = PaiseField()


class ScheduleSerializer(serializers.Serializer):
    financial_year = serializers.IntegerField(help_text="The starting year: 2025 is FY 2025-26.")
    rows = ScheduleRowSerializer(many=True)
    total_depreciation_paise = PaiseField()
    total_depreciation_display = serializers.CharField()
    total_closing_paise = PaiseField()
    total_closing_display = serializers.CharField()


def asset_payload(asset) -> dict:
    return {
        "id": asset.pk,
        "name": asset.name,
        "ledger": asset.ledger_id,
        "ledger_name": asset.ledger.name,
        "bill": asset.bill_id,
        "cost_paise": asset.cost_paise,
        "cost_display": format_inr(asset.cost_paise),
        "residual_paise": asset.residual_paise,
        "put_to_use": asset.put_to_use,
        "method": asset.method,
        "method_display": asset.get_method_display(),
        "life_years": asset.life_years,
        "rate_bp": asset.rate_bp,
        "disposed_on": asset.disposed_on,
        "disposal_paise": asset.disposal_paise,
    }


def schedule_payload(year: int, items) -> dict:
    rows = [
        {
            "asset": asset_payload(i.asset),
            "days_in_use": i.row.days_in_use,
            "opening_paise": i.row.opening_paise,
            "opening_display": format_inr(i.row.opening_paise),
            "depreciation_paise": i.row.depreciation_paise,
            "depreciation_display": format_inr(i.row.depreciation_paise),
            "closing_paise": i.row.closing_paise,
            "closing_display": format_inr(i.row.closing_paise),
            "accumulated_paise": i.row.accumulated_paise,
        }
        for i in items
    ]
    total = sum(r["depreciation_paise"] for r in rows)
    closing = sum(r["closing_paise"] for r in rows)
    return {
        "financial_year": year,
        "rows": rows,
        "total_depreciation_paise": total,
        "total_depreciation_display": format_inr(total),
        "total_closing_paise": closing,
        "total_closing_display": format_inr(closing),
    }


class DepreciationStatusSerializer(serializers.Serializer):
    year = serializers.IntegerField(help_text="Starting year: 2025 is FY 2025-26.")
    planned_paise = PaiseField(help_text="What the register says the year's depreciation is now.")
    planned_display = serializers.CharField()
    posted_paise = PaiseField(allow_null=True, help_text="What was booked, or null if the year is not booked.")
    posted_display = serializers.CharField(allow_null=True)
    entry = serializers.UUIDField(allow_null=True, help_text="The journal entry that booked it.")
    stale = serializers.BooleanField(help_text="The register has changed since it was booked: remove the posting and book it again.")


class DepreciationYearSerializer(serializers.Serializer):
    fy = serializers.IntegerField(required=False, help_text="Starting year: 2025 is FY 2025-26. Default the current year.")
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


def depreciation_payload(status: dict) -> dict:
    from core.money import format_inr

    return {
        **status,
        "planned_display": format_inr(status["planned_paise"]),
        "posted_display": format_inr(status["posted_paise"]) if status["posted_paise"] is not None else None,
    }
