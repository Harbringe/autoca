"""A client's own voucher types, number formats and voucher classes."""

from __future__ import annotations

import re

from rest_framework import serializers

from ledger.models import CustomVoucherType, VoucherType
from ledger.numbering import VoucherTypeInUseError, is_in_use
from ledger.tally_parse import normal_name
from ledger.tally_plan import NO_ACCOUNTING_TYPES, OWN_SERIES_PARENTS, STANDARD_TYPES


class CustomVoucherTypeSerializer(serializers.ModelSerializer):
    in_use = serializers.SerializerMethodField(help_text="Vouchers are numbered under it, so its name and parent can no longer change.")

    class Meta:
        model = CustomVoucherType
        fields = ["id", "name", "parent", "in_use", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_in_use(self, obj) -> bool:
        return is_in_use(obj)

    def validate_name(self, value):
        name = " ".join(value.split())
        key = normal_name(name)
        if not name:
            raise serializers.ValidationError("Give the voucher type a name.")
        if key in STANDARD_TYPES or key in NO_ACCOUNTING_TYPES or key == "reversing journal":
            raise serializers.ValidationError("That is one of Tally's own voucher types; a type of the firm's own needs a different name.")
        return name

    def validate_parent(self, value):
        if normal_name(value) not in OWN_SERIES_PARENTS:
            raise serializers.ValidationError(
                "A bank voucher type keeps the standard Payment, Receipt or Contra numbers; choose Sales, Purchase, a note, or Journal."
            )
        return value

    def validate(self, attrs):
        client = self.context["view"].client
        name = attrs.get("name")
        if name is not None:
            clash = CustomVoucherType.objects.filter(firm_id=client.firm_id, client=client).exclude(pk=getattr(self.instance, "pk", None))
            if any(normal_name(t.name) == normal_name(name) for t in clash):
                raise serializers.ValidationError({"name": "This client already has a voucher type with that name."})
        if self.instance is not None and is_in_use(self.instance):
            changing = {k for k, v in attrs.items() if getattr(self.instance, k) != v}
            if changing:
                raise VoucherTypeInUseError("Vouchers are numbered under this type, so its name and parent cannot change.")
        return attrs



_PREFIX = re.compile(r"^(?:[A-Za-z0-9/_.\-]|\{fy\})*$")


class NumberingItemSerializer(serializers.Serializer):
    voucher_type = serializers.ChoiceField(choices=VoucherType.choices)
    type_name = serializers.CharField(allow_blank=True, max_length=64, default="")
    prefix = serializers.CharField(
        allow_blank=True, max_length=16, default="", help_text="Letters, digits and / _ . - only; {fy} becomes the financial year, 25-26."
    )
    padding = serializers.IntegerField(min_value=0, max_value=8, default=0, help_text="Zero-pad the number to this many digits; 0 for none.")
    example = serializers.CharField(read_only=True, help_text="The next number in this series as it will read.")

    def validate_prefix(self, value):
        if not _PREFIX.match(value):
            raise serializers.ValidationError("Use letters, digits and / _ . - only, with {fy} for the financial year.")
        return value
