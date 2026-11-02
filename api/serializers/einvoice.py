"""Drafts of the e-invoice and e-way bill JSON for one invoice."""

from __future__ import annotations

import re

from rest_framework import serializers

PIN = re.compile(r"^[1-9][0-9]{5}$")


class EDocumentDetailsSerializer(serializers.Serializer):
    """What the books do not hold, supplied for this invoice. Everything is optional: what is left out is listed as missing."""

    seller_address = serializers.CharField(required=False, allow_blank=True, max_length=100)
    seller_place = serializers.CharField(required=False, allow_blank=True, max_length=60)
    seller_pin = serializers.CharField(required=False, allow_blank=True, max_length=6)
    buyer_address = serializers.CharField(required=False, allow_blank=True, max_length=100)
    buyer_place = serializers.CharField(required=False, allow_blank=True, max_length=60)
    buyer_pin = serializers.CharField(required=False, allow_blank=True, max_length=6)
    distance_km = serializers.IntegerField(required=False, min_value=0, max_value=4000)
    mode = serializers.ChoiceField(choices=["ROAD", "RAIL", "AIR", "SHIP"], required=False)
    vehicle_no = serializers.CharField(required=False, allow_blank=True, max_length=15)
    transporter_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    transporter_id = serializers.CharField(required=False, allow_blank=True, max_length=15)

    def _pin(self, value):
        if value and not PIN.match(value):
            raise serializers.ValidationError("A pincode is six digits and does not start with zero.")
        return value

    def validate_seller_pin(self, value):
        return self._pin(value)

    def validate_buyer_pin(self, value):
        return self._pin(value)


class EDocumentSerializer(serializers.Serializer):
    json = serializers.JSONField(help_text="The file to upload to the portal, as far as the books can fill it.")
    missing = serializers.ListField(child=serializers.CharField(), help_text="What a person must supply before it is uploaded.")


class EWayBillSerializer(EDocumentSerializer):
    required = serializers.BooleanField(help_text="The invoice is over Rs 50,000, so goods moving on it need an e-way bill.")


class EDocumentsSerializer(serializers.Serializer):
    eligible = serializers.BooleanField()
    note = serializers.CharField()
    e_invoice = EDocumentSerializer(allow_null=True)
    eway_bill = EWayBillSerializer(allow_null=True)
