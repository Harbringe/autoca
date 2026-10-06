"""Counterparties found in a client's statements, proposed as parties for a person to confirm."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from classify.models import PartyRole
from core.money import format_inr


class FoundPartySerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The counterparty as the bank spelled it.")
    count = serializers.IntegerField(help_text="How many rows of this client's statements are with them.")
    paid_paise = PaiseField(help_text="Total the client paid them.")
    paid_display = serializers.CharField()
    received_paise = PaiseField(help_text="Total the client received from them.")
    received_display = serializers.CharField()
    first = serializers.DateField()
    last = serializers.DateField()
    suggested_role = serializers.ChoiceField(
        choices=PartyRole.choices, help_text="From the direction of the money: paid out is a supplier, received a customer."
    )


class FoundPartiesSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    candidates = FoundPartySerializer(many=True)


class WantedPartySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    role = serializers.ChoiceField(choices=PartyRole.choices, required=False, default=PartyRole.VENDOR)


class CreatePartiesSerializer(serializers.Serializer):
    parties = WantedPartySerializer(many=True, allow_empty=False, max_length=500)


class CreatedPartiesSerializer(serializers.Serializer):
    created = serializers.IntegerField(help_text="Parties made or found, one per name ticked.")


def candidates_payload(items) -> dict:
    return {
        "count": len(items),
        "candidates": [
            {
                "name": c.name,
                "count": c.count,
                "paid_paise": c.paid_paise,
                "paid_display": format_inr(c.paid_paise),
                "received_paise": c.received_paise,
                "received_display": format_inr(c.received_paise),
                "first": c.first,
                "last": c.last,
                "suggested_role": c.role,
            }
            for c in items
        ],
    }
