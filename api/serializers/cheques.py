"""Cheques the client issued or received."""

from __future__ import annotations

import datetime

from rest_framework import serializers

from api.fields import PaiseField
from banking.models import BankAccount
from ledger.models import Cheque, ChequeStatus

STALE_AFTER_DAYS = 92  # a cheque is valid for three months from its date


class ChequeSerializer(serializers.ModelSerializer):
    bank_label = serializers.SerializerMethodField()
    party_name = serializers.CharField(source="party.canonical_name", read_only=True, default="")
    print_name = serializers.SerializerMethodField(help_text="Who the cheque is made out to: the name typed for it, else the party's.")
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_post_dated = serializers.SerializerMethodField()
    is_stale = serializers.SerializerMethodField(help_text="Still not presented more than three months after its date.")
    amount_paise = PaiseField(min_value=1)

    class Meta:
        model = Cheque
        fields = [
            "id", "bank_account", "bank_label", "direction", "number", "cheque_date", "issued_on", "amount_paise", "party", "party_name",
            "payee_name", "print_name", "status", "status_display", "status_on", "note", "is_post_dated", "is_stale",
        ]
        read_only_fields = ["id", "status", "status_on"]
        extra_kwargs = {"issued_on": {"required": False}}

    def get_bank_label(self, obj) -> str:
        return f"{obj.bank_account.bank_code} ••••{obj.bank_account.account_last4}"

    def get_print_name(self, obj) -> str:
        return obj.payee_name or (obj.party.canonical_name if obj.party_id else "")

    def get_is_post_dated(self, obj) -> bool:
        return obj.cheque_date > obj.issued_on

    def get_is_stale(self, obj) -> bool:
        return obj.status == ChequeStatus.PENDING and (datetime.date.today() - obj.cheque_date).days > STALE_AFTER_DAYS

    def validate_number(self, value):
        value = value.strip()
        if not value or not value.isalnum():
            raise serializers.ValidationError("A cheque number is letters and digits only.")
        return value

    def validate_payee_name(self, value):
        return " ".join(value.split())

    def validate(self, attrs):
        client = self.context["view"].client
        account = attrs.get("bank_account", getattr(self.instance, "bank_account", None))
        if account is not None and (account.client_id != client.pk or account.firm_id != client.firm_id):
            raise serializers.ValidationError({"bank_account": "That account belongs to another client."})
        party = attrs.get("party")
        if party is not None and party.client_id != client.pk:
            raise serializers.ValidationError({"party": "That party belongs to another client."})
        if self.instance is None:
            attrs.setdefault("issued_on", datetime.date.today())
        number = attrs.get("number", getattr(self.instance, "number", None))
        direction = attrs.get("direction", getattr(self.instance, "direction", None))
        if account is not None and number and direction:
            clash = Cheque.objects.filter(firm_id=client.firm_id, client=client, bank_account=account, direction=direction, number=number)
            if clash.exclude(pk=getattr(self.instance, "pk", None)).exists():
                raise serializers.ValidationError({"number": "That cheque number is already recorded for this account."})
        if self.instance is not None and self.instance.status != ChequeStatus.PENDING:
            raise serializers.ValidationError("A cheque that is no longer pending cannot be changed; set it back to pending first.")
        return attrs


class ChequeStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ChequeStatus.choices)
    on = serializers.DateField(required=False, help_text="The day it cleared, bounced or was cancelled; today when left out.")


class PdcMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    issued_paise = PaiseField()
    received_paise = PaiseField()


class PdcSerializer(serializers.Serializer):
    issued_paise = PaiseField(help_text="Post-dated cheques the client issued that are still pending.")
    received_paise = PaiseField(help_text="Post-dated cheques the client received that are still pending.")
    by_month = PdcMonthSerializer(many=True)
    due_soon = ChequeSerializer(many=True)
    stale = ChequeSerializer(many=True)


class BankAccountChoiceSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = BankAccount
        fields = ["id", "label"]

    def get_label(self, obj) -> str:
        return f"{obj.bank_code} ••••{obj.account_last4}"
