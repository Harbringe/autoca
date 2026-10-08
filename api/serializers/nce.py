"""The financial statements in the ICAI format for non-corporate entities."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from api.serializers.ledger import ReportFooterSerializer


class StatementRowSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.ChoiceField(choices=["heading", "line", "subtotal", "total"])
    level = serializers.IntegerField(help_text="Indentation, from 0.")
    note = serializers.IntegerField(allow_null=True, help_text="The note this line is explained in.")
    current_paise = PaiseField(allow_null=True)
    previous_paise = PaiseField(allow_null=True)


class NoteRowSerializer(serializers.Serializer):
    label = serializers.CharField()
    ledger = serializers.UUIDField(source="ledger_id", allow_null=True, help_text="The ledger, to open it.")
    current_paise = PaiseField()
    previous_paise = PaiseField()


class NoteSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    title = serializers.CharField()
    rows = NoteRowSerializer(many=True)
    total_current_paise = PaiseField()
    total_previous_paise = PaiseField()


class RegroupingSerializer(serializers.Serializer):
    ledger = serializers.UUIDField(source="ledger_id")
    name = serializers.CharField()
    previous_line = serializers.CharField()
    current_line = serializers.CharField()
    previous_paise = PaiseField()
    current_paise = PaiseField()
    text = serializers.CharField(help_text="The disclosure, drafted: where it was shown, where it is shown now, and why.")


class StatementsSerializer(serializers.Serializer):
    balance_sheet = StatementRowSerializer(many=True)
    profit_and_loss = StatementRowSerializer(many=True)
    notes = NoteSerializer(many=True)
    regroupings = RegroupingSerializer(many=True)
    footer = ReportFooterSerializer()
    has_previous = serializers.BooleanField(help_text="False for the first year of books: there is nothing to compare with.")
    balances = serializers.BooleanField(help_text="Total liabilities equal total assets.")
    suspense_paise = PaiseField(help_text="What sits in Suspense, shown on Other current assets or liabilities and warned about.")
