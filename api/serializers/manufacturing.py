"""Bills of materials and production runs."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from api.fields import PaiseField
from ledger.models import BillOfMaterials


class ComponentSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=Decimal("0.001"))


class BomSerializer(serializers.ModelSerializer):
    components = ComponentSerializer(many=True, allow_empty=False, max_length=50)
    output_quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=Decimal("0.001"), default=1)

    class Meta:
        model = BillOfMaterials
        fields = ["id", "name", "unit", "output_quantity", "components"]
        read_only_fields = ["id"]

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Name the finished item.")
        return name

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["components"] = [{"name": c["name"], "unit": c.get("unit", ""), "quantity": f"{Decimal(str(c['quantity'])):.3f}"} for c in instance.components]
        return data

    def validate(self, attrs):
        client = self.context["view"].client
        name = attrs.get("name", getattr(self.instance, "name", ""))
        components = attrs.get("components")
        if components is not None:
            seen = set()
            for c in components:
                c["name"] = " ".join(c["name"].split())
                key = c["name"].lower()
                if not c["name"]:
                    raise serializers.ValidationError({"components": "Name each component."})
                if key in seen:
                    raise serializers.ValidationError({"components": f"{c['name']} is listed twice."})
                if key == name.lower():
                    raise serializers.ValidationError({"components": "A finished item cannot be made from itself."})
                seen.add(key)
            attrs["components"] = [{"name": c["name"], "unit": c.get("unit", ""), "quantity": str(c["quantity"])} for c in components]
        if "name" in attrs:
            clash = BillOfMaterials.objects.filter(firm_id=client.firm_id, client=client, name__iexact=attrs["name"]).exclude(pk=getattr(self.instance, "pk", None))
            if clash.exists():
                raise serializers.ValidationError({"name": "This client already has a bill of materials for that item."})
        return attrs


class RunComponentSerializer(serializers.Serializer):
    name = serializers.CharField()
    unit = serializers.CharField(allow_blank=True)
    needed = serializers.CharField()
    available = serializers.CharField()
    cost_paise = PaiseField()
    enough = serializers.BooleanField()


class RunPlanSerializer(serializers.Serializer):
    quantity = serializers.CharField()
    components = RunComponentSerializer(many=True)
    cost_paise = PaiseField(help_text="What the components cost at their average, before any extra cost.")
    short = serializers.ListField(child=serializers.CharField())


class ProduceSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3, min_value=Decimal("0.001"))
    entry_date = serializers.DateField()
    godown = serializers.UUIDField(required=False, allow_null=True, default=None)
    extra_cost_paise = PaiseField(min_value=0, default=0, help_text="Labour, power and the like added to the finished goods' cost.")
    note = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


def decimal_text(value) -> str:
    try:
        return f"{Decimal(value).normalize():f}"
    except InvalidOperation:
        return str(value)
