"""Opening stock and count adjustments."""

from __future__ import annotations

from rest_framework import serializers

from ledger.models import Godown, StockEntry, StockEntryKind, StockItem


class StockEntrySerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    godown_name = serializers.CharField(source="godown.name", read_only=True, default="")

    class Meta:
        model = StockEntry
        fields = ["id", "kind", "kind_display", "entry_date", "direction", "name", "unit", "quantity", "value_paise", "note", "godown", "godown_name", "transfer"]
        read_only_fields = fields


class StockEntryCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[c for c in StockEntryKind.choices if c[0] != StockEntryKind.TRANSFER])
    entry_date = serializers.DateField()
    direction = serializers.ChoiceField(choices=["IN", "OUT"], default="IN", help_text="Ignored for opening stock, which is always in.")
    name = serializers.CharField(max_length=200)
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=0)
    value_paise = serializers.IntegerField(min_value=0, default=0, help_text="What the stock is carried at.")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    godown = serializers.PrimaryKeyRelatedField(queryset=Godown.objects.all(), required=False, allow_null=True, default=None, help_text="Empty is the main location.")


class StockTransferSerializer(serializers.Serializer):
    entry_date = serializers.DateField()
    name = serializers.CharField(max_length=200)
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=0)
    from_godown = serializers.PrimaryKeyRelatedField(queryset=Godown.objects.all(), allow_null=True, help_text="Empty is the main location.")
    to_godown = serializers.PrimaryKeyRelatedField(queryset=Godown.objects.all(), allow_null=True, help_text="Empty is the main location.")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class StockCountSerializer(serializers.Serializer):
    entry_date = serializers.DateField()
    name = serializers.CharField(max_length=200)
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    counted_quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=0)
    godown = serializers.PrimaryKeyRelatedField(queryset=Godown.objects.all(), required=False, allow_null=True, default=None)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class StockCountResultSerializer(serializers.Serializer):
    book_quantity = serializers.CharField(help_text="What the books said was on hand.")
    counted_quantity = serializers.CharField()
    difference = serializers.CharField(help_text="Counted minus book: negative is a shortage.")
    entry = StockEntrySerializer(allow_null=True, help_text="The adjustment booked; null when the count agreed with the books.")


class GodownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Godown
        fields = ["id", "name"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Name the godown.")
        return name

    def validate(self, attrs):
        client = self.context["view"].client
        name = attrs.get("name")
        if name is not None:
            clash = Godown.objects.filter(firm_id=client.firm_id, client=client, name__iexact=name).exclude(pk=getattr(self.instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError({"name": "This client already has a godown with that name."})
        return attrs


class StockItemSerializer(serializers.ModelSerializer):
    """A product the client buys or sells: its name, unit, HSN, GST rate, reorder level and the ledgers it is booked to."""

    purchase_ledger_name = serializers.CharField(source="purchase_ledger.name", read_only=True, default="")
    sales_ledger_name = serializers.CharField(source="sales_ledger.name", read_only=True, default="")

    class Meta:
        model = StockItem
        fields = [
            "id", "name", "unit", "hsn_sac", "gst_rate", "reorder_level",
            "purchase_ledger", "purchase_ledger_name", "sales_ledger", "sales_ledger_name",
        ]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Name the item.")
        return name

    def validate_gst_rate(self, value):
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError("A GST rate is between 0 and 100.")
        return value

    def validate_reorder_level(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("A reorder level cannot be negative.")
        return value

    def validate(self, attrs):
        client = self.context["view"].client
        for field in ("purchase_ledger", "sales_ledger"):
            ledger = attrs.get(field)
            if ledger is not None and ledger.client_id != client.pk:
                raise serializers.ValidationError({field: "That ledger belongs to another client."})
        name = attrs.get("name")
        if name is not None:
            clash = StockItem.objects.filter(firm_id=client.firm_id, client=client, name__iexact=name).exclude(pk=getattr(self.instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError({"name": "This client already has an item with that name."})
        return attrs

