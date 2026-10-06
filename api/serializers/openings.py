"""A party's opening balance, and breaking it into the bills it is made of."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr


class OpeningBillSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=64, help_text="The invoice number on the supplier's (or our) invoice.")
    bill_date = serializers.DateField(help_text="The invoice date. Must be before the date the opening balance stands at.")
    amount_paise = PaiseField(min_value=1, help_text="Whole paise still owing on that invoice.")
    due_date = serializers.DateField(required=False, allow_null=True, default=None)


class OpeningBillsRequestSerializer(serializers.Serializer):
    bills = OpeningBillSerializer(many=True, max_length=200, allow_empty=False)


class OpeningStandingSerializer(serializers.Serializer):
    financial_year = serializers.IntegerField(allow_null=True, help_text="The year the balance stands at the start of.")
    direction = serializers.ChoiceField(
        choices=["DR", "CR"], allow_null=True, help_text="DR: the party owes the client. CR: the client owes the party."
    )
    opening_paise = PaiseField(help_text="Signed like the ledger: debits positive.")
    opening_display = serializers.CharField()
    billed_paise = PaiseField(help_text="How much is already broken into bills.")
    remaining_paise = PaiseField(help_text="How much is not.")
    remaining_display = serializers.CharField()


def standing_payload(standing) -> dict:
    return {
        "financial_year": standing.financial_year,
        "direction": standing.direction,
        "opening_paise": standing.opening_paise,
        "opening_display": format_inr(abs(standing.opening_paise)),
        "billed_paise": standing.billed_paise,
        "remaining_paise": max(standing.remaining_paise, 0),
        "remaining_display": format_inr(max(standing.remaining_paise, 0)),
    }
