"""Settling bills with a payment: what the screen shows, and what a person sends back.

A payment on a supplier's or customer's own account says nothing about which invoices it pays. The API gives the review
screen the party's open bills and a *proposal* of how the payment would clear them, and takes back a person's decision.
The proposal is only a suggestion: nothing is allocated, or posted to a party's account, until a person sends a settlement.
"""

from __future__ import annotations

from rest_framework import serializers

from api.fields import MoneySerializerMixin, PaiseField
from ledger.models import AllocationKind, Bill

HOLD_CHOICES = [
    (AllocationKind.ON_ACCOUNT.value, "Held on account"),
    (AllocationKind.ADVANCE.value, "An advance"),
]


class SettlementAllocationSerializer(serializers.Serializer):
    bill = serializers.UUIDField()
    amount_paise = PaiseField(min_value=1, help_text="How much of this bill the payment clears.")


class SettlementSerializer(serializers.Serializer):
    """A person's decision about what one payment or receipt on a party's account is for."""

    allocations = SettlementAllocationSerializer(many=True, required=False, default=list)
    remainder = serializers.ChoiceField(
        choices=HOLD_CHOICES, required=False, allow_null=True, default=None,
        help_text=(
            "What to do with the part of the payment no bill takes: hold it on account, or treat it as an advance. "
            "Required when the bills do not add up to the whole amount."
        ),
    )


class RowSettlementSerializer(SettlementSerializer):
    classification = serializers.UUIDField(help_text="The row this decision is for.")


class OpenBillSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = ("total_paise", "open_paise")

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    open_paise = PaiseField(read_only=True)

    class Meta:
        model = Bill
        fields = ["id", "kind", "kind_display", "reference", "bill_date", "due_date", "total_paise", "open_paise"]
        read_only_fields = fields


class ProposedAllocationSerializer(serializers.Serializer):
    bill = serializers.UUIDField()
    amount_paise = PaiseField()
    amount_display = serializers.CharField()


class ProposalSerializer(serializers.Serializer):
    allocations = ProposedAllocationSerializer(many=True)
    remainder_paise = PaiseField(help_text="What is left after the bills, to be held on account or as an advance.")
    remainder_display = serializers.CharField()
    basis = serializers.ChoiceField(
        choices=["exact_one", "exact_set", "oldest_first", "none"],
        help_text=(
            "How sure the suggestion is: one bill is exactly this amount; a small set adds up to it exactly; the oldest "
            "bills filled in date order; or there is nothing open to settle."
        ),
    )


class PartyRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class SettlementContextSerializer(serializers.Serializer):
    """Everything the screen needs to ask the question and suggest an answer."""

    party = PartyRefSerializer()
    amount_paise = PaiseField(help_text="What moved, in whole paise.")
    amount_display = serializers.CharField()
    direction = serializers.ChoiceField(
        choices=["DR", "CR"], help_text="The side of the party's account the payment lands on."
    )
    bills = OpenBillSerializer(many=True)
    proposal = ProposalSerializer()
    already_allocated_paise = PaiseField(help_text="For an entry already posted: how much of it is already allocated.")


class SettleEntrySerializer(SettlementSerializer):
    """Settle the unallocated part of an entry that is already posted."""


class SettledSerializer(serializers.Serializer):
    settled_paise = PaiseField(help_text="How much of the entry was allocated by this request.")
    settled_display = serializers.CharField()
    fully_allocated = serializers.BooleanField(help_text="Nothing of the entry is left unallocated.")
