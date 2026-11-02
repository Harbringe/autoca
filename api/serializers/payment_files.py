"""Where to pay a party, and the bank payment file built from open payables."""

from __future__ import annotations

import datetime
import re

from rest_framework import serializers

from api.fields import PaiseField

MODES = ("NEFT", "RTGS", "IMPS")
IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


class PaymentDetailsSerializer(serializers.Serializer):
    """Read: the last four digits only. Write: the whole account number, which is stored encrypted and never returned."""

    account_number = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=34)
    ifsc = serializers.CharField(required=False, allow_blank=True, max_length=11)
    account_name = serializers.CharField(required=False, allow_blank=True, max_length=200, help_text="The name the bank holds the account in.")
    account_last4 = serializers.CharField(read_only=True)
    ready = serializers.BooleanField(read_only=True, help_text="An account number, an IFSC and a name are all present.")

    def validate_ifsc(self, value):
        value = value.strip().upper()
        if value and not IFSC.match(value):
            raise serializers.ValidationError("An IFSC is 11 characters: four letters, a zero, then six letters or digits.")
        return value

    def validate_account_number(self, value):
        cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
        if value.strip() and not (8 <= len(cleaned) <= 24):
            raise serializers.ValidationError("An account number is 8 to 24 characters.")
        return value


class PayableSerializer(serializers.Serializer):
    party = serializers.UUIDField()
    name = serializers.CharField()
    open_paise = PaiseField(help_text="What is owed to the party on its open bills.")
    bills = serializers.IntegerField()
    ready = serializers.BooleanField(help_text="Whether the party has the bank details a payment needs.")
    account_last4 = serializers.CharField()


class PaymentItemSerializer(serializers.Serializer):
    party = serializers.UUIDField()
    amount_paise = PaiseField(min_value=1)
    narration = serializers.CharField(required=False, allow_blank=True, max_length=60)


class PaymentFileSerializer(serializers.Serializer):
    bank_account = serializers.UUIDField(help_text="The client's account the money is paid from.")
    mode = serializers.ChoiceField(choices=MODES)
    payment_date = serializers.DateField()
    items = PaymentItemSerializer(many=True, min_length=1, max_length=500)

    def validate_payment_date(self, value):
        if value < datetime.date.today() - datetime.timedelta(days=1):
            raise serializers.ValidationError("A payment cannot be dated in the past.")
        return value
