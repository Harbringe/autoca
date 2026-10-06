"""The close page: controls, open items and the reasons given for them."""

from __future__ import annotations

from rest_framework import serializers

from api.serializers.openitems import OpenItemLinkSerializer
from core.money import format_inr


class CloseCheckSerializer(serializers.Serializer):
    name = serializers.CharField()
    title = serializers.CharField()
    ok = serializers.BooleanField()
    detail = serializers.CharField(allow_blank=True)


class CloseItemSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Names this item for `explain`; stable for as long as it is the same item.")
    kind = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()
    amount_paise = serializers.IntegerField(allow_null=True)
    amount_display = serializers.CharField(allow_null=True)
    since = serializers.DateField(allow_null=True)
    link = OpenItemLinkSerializer(allow_null=True)
    blocking = serializers.BooleanField(help_text="Sign-off waits until this is fixed or explained.")
    explained = serializers.BooleanField()
    note = serializers.CharField(allow_blank=True, help_text="Why it can stand, when someone has said.")
    explained_by = serializers.CharField(allow_blank=True)


class CloseReportSerializer(serializers.Serializer):
    through = serializers.DateField(allow_null=True, help_text="The date the report is as at: the latest entry unless asked.")
    ready = serializers.BooleanField(help_text="Every control passes and no blocking item is unexplained.")
    unexplained_blocking = serializers.IntegerField()
    checks = CloseCheckSerializer(many=True)
    items = CloseItemSerializer(many=True)


class ExplainSerializer(serializers.Serializer):
    item_key = serializers.CharField(max_length=200)
    note = serializers.CharField(max_length=500, help_text="Why this can stand, in a few words.")


class WithdrawSerializer(serializers.Serializer):
    item_key = serializers.CharField(max_length=200)


def report_payload(report) -> dict:
    return {
        "through": report.through,
        "ready": report.ready,
        "unexplained_blocking": report.unexplained_blocking,
        "checks": [{"name": c.name, "title": c.title, "ok": c.ok, "detail": c.detail} for c in report.checks],
        "items": [
            {
                "key": i.key,
                "kind": i.item.kind,
                "title": i.title,
                "summary": i.item.summary,
                "amount_paise": i.item.amount_paise,
                "amount_display": format_inr(i.item.amount_paise) if i.item.amount_paise is not None else None,
                "since": i.item.since,
                "link": i.item.link,
                "blocking": i.blocking,
                "explained": i.explained,
                "note": i.note,
                "explained_by": i.explained_by,
            }
            for i in report.items
        ],
    }
