"""Outstanding payables and receivables, and a party's statement of account.

Money is whole paise with a ``*_display`` string beside it, as everywhere else. These are computed on request from the bills
and settlements as they stood on the date asked for, so an old date gives the old answer.
"""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr


class OutstandingBillSerializer(serializers.Serializer):
    bill = serializers.UUIDField()
    reference = serializers.CharField()
    kind = serializers.CharField()
    kind_display = serializers.CharField()
    bill_date = serializers.DateField()
    due_date = serializers.DateField(allow_null=True)
    age_days = serializers.IntegerField(help_text="Days from the bill date to the report date.")
    bucket = serializers.CharField(help_text="The ageing bucket: 0-30, 31-60, 61-90 or Over 90.")
    open_paise = PaiseField(help_text="Still owing on the report date. Negative for a note that reverses a bill.")
    open_display = serializers.CharField()


class OutstandingPartySerializer(serializers.Serializer):
    party = serializers.UUIDField()
    name = serializers.CharField()
    gstin_last4 = serializers.CharField(allow_blank=True)
    bills = OutstandingBillSerializer(many=True)
    bucket_paise = serializers.DictField(child=PaiseField(), help_text="What is owing in each ageing bucket.")
    on_account_paise = PaiseField(help_text="Money held on account or as an advance, as a negative: it reduces what is owed.")
    on_account_display = serializers.CharField()
    total_paise = PaiseField()
    total_display = serializers.CharField()


class OutstandingSerializer(serializers.Serializer):
    side = serializers.ChoiceField(choices=["payables", "receivables"])
    as_of = serializers.DateField()
    buckets = serializers.ListField(child=serializers.CharField(), help_text="The ageing buckets, in reading order.")
    parties = OutstandingPartySerializer(many=True)
    bucket_paise = serializers.DictField(child=PaiseField())
    on_account_paise = PaiseField()
    on_account_display = serializers.CharField()
    total_paise = PaiseField()
    total_display = serializers.CharField()


class PartyStatementRowSerializer(serializers.Serializer):
    date = serializers.DateField()
    voucher_type = serializers.CharField()
    entry_no = serializers.IntegerField()
    narration = serializers.CharField(allow_blank=True)
    debit_paise = PaiseField()
    debit_display = serializers.CharField()
    credit_paise = PaiseField()
    credit_display = serializers.CharField()
    balance_paise = PaiseField(help_text="Debits positive, like the ledger: an amount owed to the party is negative.")
    balance_display = serializers.CharField()
    entry = serializers.UUIDField()
    bill = serializers.UUIDField(allow_null=True, help_text="The bill this voucher booked, if it booked one.")


class PartyStatementSerializer(serializers.Serializer):
    party = serializers.UUIDField()
    name = serializers.CharField()
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    opening_paise = PaiseField()
    opening_display = serializers.CharField()
    rows = PartyStatementRowSerializer(many=True)
    total_debit_paise = PaiseField()
    total_debit_display = serializers.CharField()
    total_credit_paise = PaiseField()
    total_credit_display = serializers.CharField()
    closing_paise = PaiseField()
    closing_display = serializers.CharField()


def outstanding_payload(report) -> dict:
    """An ``Outstanding`` as the dict the serializers describe."""
    from ledger.partyreports import BUCKET_LABELS

    return {
        "side": report.side,
        "as_of": report.as_of,
        "buckets": list(BUCKET_LABELS),
        "parties": [
            {
                "party": entry.party.pk,
                "name": entry.party.canonical_name,
                "gstin_last4": entry.party.gstin[-4:] if entry.party.gstin else "",
                "bills": [
                    {
                        "bill": item.bill.pk,
                        "reference": item.bill.reference,
                        "kind": item.bill.kind,
                        "kind_display": item.bill.get_kind_display(),
                        "bill_date": item.bill.bill_date,
                        "due_date": item.bill.due_date,
                        "age_days": item.age_days,
                        "bucket": item.bucket,
                        "open_paise": item.open_paise,
                        "open_display": format_inr(item.open_paise),
                    }
                    for item in entry.bills
                ],
                "bucket_paise": {label: entry.bucket_paise(label) for label in BUCKET_LABELS},
                "on_account_paise": entry.on_account_paise,
                "on_account_display": format_inr(entry.on_account_paise),
                "total_paise": entry.total_paise,
                "total_display": format_inr(entry.total_paise),
            }
            for entry in report.parties
        ],
        "bucket_paise": {label: report.bucket_paise(label) for label in BUCKET_LABELS},
        "on_account_paise": report.on_account_paise,
        "on_account_display": format_inr(report.on_account_paise),
        "total_paise": report.total_paise,
        "total_display": format_inr(report.total_paise),
    }


def statement_payload(statement) -> dict:
    return {
        "party": statement.party.pk,
        "name": statement.party.canonical_name,
        "date_from": statement.date_from,
        "date_to": statement.date_to,
        "opening_paise": statement.opening_paise,
        "opening_display": format_inr(statement.opening_paise),
        "rows": [
            {
                "date": row.date,
                "voucher_type": row.voucher_type,
                "entry_no": row.entry_no,
                "narration": row.narration,
                "debit_paise": row.debit_paise,
                "debit_display": format_inr(row.debit_paise),
                "credit_paise": row.credit_paise,
                "credit_display": format_inr(row.credit_paise),
                "balance_paise": row.balance_paise,
                "balance_display": format_inr(row.balance_paise),
                "entry": row.entry_id,
                "bill": row.bill_id,
            }
            for row in statement.rows
        ],
        "total_debit_paise": statement.total_debit_paise,
        "total_debit_display": format_inr(statement.total_debit_paise),
        "total_credit_paise": statement.total_credit_paise,
        "total_credit_display": format_inr(statement.total_credit_paise),
        "closing_paise": statement.closing_paise,
        "closing_display": format_inr(statement.closing_paise),
    }
