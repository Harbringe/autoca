"""Everything that does not yet tie out, as one list.

Each module registers detectors for what can be left unmatched about its documents (``ledger.openitems``); this is how that
list reaches the screen. Items are computed on request and never stored, so one that has been fixed is simply not there.
"""

from __future__ import annotations

import datetime

from rest_framework import serializers

from api.fields import PaiseField
from classify.models import BillStatus
from core.money import format_inr


class OpenItemLinkSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=["bill", "entry", "party", "invoice"],
        help_text="What to open to fix it: a bill, a posted entry, a party's account, or an uploaded invoice.",
    )
    id = serializers.UUIDField()


class OpenItemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    title = serializers.CharField(help_text="What this kind of item is, in a few words.")
    summary = serializers.CharField(help_text="What is unmatched and about whom, as a sentence a CA can read.")
    amount_paise = PaiseField(allow_null=True)
    amount_display = serializers.CharField(allow_null=True)
    since = serializers.DateField(allow_null=True, help_text="The date it dates from.")
    age_days = serializers.IntegerField(allow_null=True, help_text="Days from then to today.")
    link = OpenItemLinkSerializer(allow_null=True)


class OpenItemKindSerializer(serializers.Serializer):
    kind = serializers.CharField()
    title = serializers.CharField()
    count = serializers.IntegerField()


class OpenItemsSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    kinds = OpenItemKindSerializer(many=True, help_text="Every kind that can be reported, with how many are open now.")
    items = OpenItemSerializer(many=True, help_text="Oldest first.")


class BillStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[(value, label) for value, label in BillStatus.choices],
        help_text=(
            "What to say about a payment booked to an expense head although the party has bills: "
            "`NO_INVOICE_EXPECTED` (a direct expense), `NEEDS_INVOICE` (it is waiting for one), or blank to unsay it."
        ),
        allow_blank=True,
    )


def open_items_payload(items, titles: dict[str, str], today: datetime.date) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return {
        "count": len(items),
        "kinds": [{"kind": kind, "title": title, "count": counts.get(kind, 0)} for kind, title in titles.items()],
        "items": [
            {
                "kind": item.kind,
                "title": titles.get(item.kind, item.kind),
                "summary": item.summary,
                "amount_paise": item.amount_paise,
                "amount_display": format_inr(item.amount_paise) if item.amount_paise is not None else None,
                "since": item.since,
                "age_days": (today - item.since).days if item.since else None,
                "link": item.link,
            }
            for item in items
        ],
    }
