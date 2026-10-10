"""Opening stock and count adjustments."""

from __future__ import annotations

from rest_framework import serializers

from ledger.models import StockEntry, StockEntryKind


class StockEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = StockEntry
        fields = ["id", "kind", "kind_display", "entry_date", "direction", "name", "unit", "quantity", "value_paise", "note"]
        read_only_fields = fields


class StockEntryCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=StockEntryKind.choices)
    entry_date = serializers.DateField()
    direction = serializers.ChoiceField(choices=["IN", "OUT"], default="IN", help_text="Ignored for opening stock, which is always in.")
    name = serializers.CharField(max_length=200)
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=0)
    value_paise = serializers.IntegerField(min_value=0, default=0, help_text="What the stock is carried at.")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
