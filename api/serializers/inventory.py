"""The stock summary: one block per item, a row per month."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from api.fields import PaiseField
from api.serializers.ledger import ReportFooterSerializer


def _qty(value) -> str:
    """A quantity as text without trailing zeros: 60, 6.5."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


class InventoryMonthSerializer(serializers.Serializer):
    month = serializers.CharField(help_text="YYYY-MM.")
    in_qty = serializers.CharField()
    in_value_paise = PaiseField()
    out_qty = serializers.CharField()
    out_value_paise = PaiseField()
    closing_qty = serializers.CharField(help_text="Negative when more was sold than was bought.")
    closing_value_paise = PaiseField()


class InventoryItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    unit = serializers.CharField(allow_blank=True)
    opening_qty = serializers.CharField()
    opening_value_paise = PaiseField()
    closing_qty = serializers.CharField()
    closing_value_paise = PaiseField()
    in_qty = serializers.CharField(help_text="Over the year.")
    in_value_paise = PaiseField()
    out_qty = serializers.CharField()
    out_value_paise = PaiseField()
    months = InventoryMonthSerializer(many=True)


class InventorySerializer(serializers.Serializer):
    footer = ReportFooterSerializer()
    items = InventoryItemSerializer(many=True)
    bills_counted = serializers.IntegerField(help_text="Purchases and sales whose invoice lines are in this report.")
    bills_left_out = serializers.IntegerField(help_text="Purchases and sales this year with no invoice lines, so no stock movement.")
    left_out_examples = serializers.ListField(child=serializers.CharField())
    lines_without_value = serializers.IntegerField(help_text="Lines with a quantity but no amount: they move stock and carry no value.")


def inventory_payload(report, footer) -> dict:
    items = []
    for item in report.items:
        in_qty = sum((m.in_qty for m in item.months), Decimal(0))
        out_qty = sum((m.out_qty for m in item.months), Decimal(0))
        items.append(
            {
                "name": item.name,
                "unit": item.unit,
                "opening_qty": _qty(item.opening_qty),
                "opening_value_paise": item.opening_value_paise,
                "closing_qty": _qty(item.closing_qty),
                "closing_value_paise": item.closing_value_paise,
                "in_qty": _qty(in_qty),
                "in_value_paise": sum(m.in_value_paise for m in item.months),
                "out_qty": _qty(out_qty),
                "out_value_paise": sum(m.out_value_paise for m in item.months),
                "months": [
                    {
                        "month": m.month,
                        "in_qty": _qty(m.in_qty),
                        "in_value_paise": m.in_value_paise,
                        "out_qty": _qty(m.out_qty),
                        "out_value_paise": m.out_value_paise,
                        "closing_qty": _qty(m.closing_qty),
                        "closing_value_paise": m.closing_value_paise,
                    }
                    for m in item.months
                ],
            }
        )
    return {
        "footer": footer,
        "items": items,
        "bills_counted": report.bills_counted,
        "bills_left_out": report.bills_left_out,
        "left_out_examples": report.left_out_examples,
        "lines_without_value": report.lines_without_value,
    }
