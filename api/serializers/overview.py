"""The firm overview: one line per client, and what the firm as a whole has waiting."""

from __future__ import annotations

from rest_framework import serializers


class OverviewLeadSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class OverviewNextStepSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=["upload", "place", "post", "sign_off", "send_for_review", "none"],
        help_text="What to do next: upload a statement, place rows in ledgers, post them, sign off, or send for review.",
    )
    label = serializers.CharField(help_text="The same words the client list shows.")
    count = serializers.IntegerField(help_text="Rows to place or post; 0 for the other steps.")


class OverviewClientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    lead = OverviewLeadSerializer(allow_null=True)
    stage = serializers.ChoiceField(
        choices=["no_statements", "needs_ledger", "ready_to_post", "in_review", "ready_for_review", "signed_off"],
    )
    next_step = OverviewNextStepSerializer()
    unresolved = serializers.IntegerField(help_text="Rows nobody has placed in a ledger.")
    pending_approval = serializers.IntegerField(help_text="Rows with a ledger, not yet posted.")
    assistant_waiting = serializers.IntegerField(help_text="Unplaced rows still queued for the assistant.")
    ai_unchecked = serializers.IntegerField(
        help_text="Entries after the last sign-off that the assistant posted or changed and nobody has checked."
    )
    review_pending = serializers.BooleanField(help_text="The books have been sent for review and not yet decided.")
    signed_off_through = serializers.DateField(allow_null=True)
    last_statement_end = serializers.DateField(allow_null=True)
    months_missing = serializers.ListField(
        child=serializers.CharField(),
        help_text="Months (YYYY-MM) inside a bank account's run of statements that none of its statements touches.",
    )


class OverviewTotalsSerializer(serializers.Serializer):
    clients = serializers.IntegerField()
    unresolved = serializers.IntegerField()
    pending_approval = serializers.IntegerField()
    assistant_waiting = serializers.IntegerField()
    ai_unchecked = serializers.IntegerField()
    review_pending = serializers.IntegerField(help_text="Clients whose books await a decision.")
    months_missing = serializers.IntegerField(help_text="Missing months summed over clients.")


class OverviewByStageSerializer(serializers.Serializer):
    no_statements = serializers.IntegerField()
    needs_ledger = serializers.IntegerField()
    ready_to_post = serializers.IntegerField()
    in_review = serializers.IntegerField()
    ready_for_review = serializers.IntegerField()
    signed_off = serializers.IntegerField()


class FirmOverviewSerializer(serializers.Serializer):
    totals = OverviewTotalsSerializer()
    by_stage = OverviewByStageSerializer()
    clients = OverviewClientSerializer(many=True)
