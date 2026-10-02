"""Measured figures for the firm: how much of the work the assistant did, and how it is going."""

from __future__ import annotations

from rest_framework import serializers


class MetricsPeriodSerializer(serializers.Serializer):
    to = serializers.DateField()

    def get_fields(self):
        # `from` is a Python keyword, so it cannot be declared as a class attribute.
        fields = super().get_fields()
        fields["from"] = serializers.DateField()
        return fields


class AttentionReasonSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=[
            "reconciliation_difference",
            "statement_month_missing",
            "assistant_entries_unchecked",
            "unsigned_too_long",
            "suspense_balance",
            "opening_balance_unconfirmed",
        ],
        help_text="reconciliation_difference: the books and the bank statement disagree at the latest "
        "statement date. statement_month_missing: a month inside a bank account's run of statements has "
        "none. assistant_entries_unchecked: entries the assistant posted or changed are not yet checked. "
        "unsigned_too_long: the books are not signed off more than 45 days after the latest entry. "
        "suspense_balance: the Suspense ledger holds a non-zero balance. opening_balance_unconfirmed: a "
        "bank account's opening balance is not confirmed. These describe where the books stand now, "
        "whatever period was asked for.",
    )
    message = serializers.CharField(help_text="A plain sentence; show it as it is.")


class MetricFiguresSerializer(serializers.Serializer):
    rows_posted = serializers.IntegerField(
        help_text="Statement rows that reached the books in the period: journal entries approved in the "
        "period that stand for a statement row, corrections excluded. A transfer between two of the "
        "client's own accounts is one entry and counts once."
    )
    rows_automated = serializers.IntegerField(
        help_text="Of those, the rows nobody posted by hand: the assistant posted them (no approving "
        "person is recorded) and no person has since edited the entry."
    )
    automation_share = serializers.FloatField(
        allow_null=True,
        help_text="rows_automated / rows_posted, between 0 and 1. Null when no row was posted in the period.",
    )
    placements_stayed = serializers.IntegerField(
        help_text="Rule or model placements posted in the period that nobody has changed: an automatic "
        "post with nothing in the change log, or an entry a person posted without changing the placement "
        "(the row still carries the rule that placed it, or the model's suggestion with no placement by "
        "a person recorded against it)."
    )
    placements_changed = serializers.IntegerField(
        help_text="Changes made in the period to a rule or model placement: a change-log item that moved "
        "an automatic entry to other ledgers, the removal of one, a correction entry against one, or a "
        "person placing a row the model had already suggested. A change that only reworded the "
        "narration is not counted."
    )
    accuracy = serializers.FloatField(
        allow_null=True,
        help_text="placements_stayed / (placements_stayed + placements_changed), between 0 and 1. Null "
        "when there is nothing to judge. Stored data cannot show a rule placement that a person "
        "overrode before posting, nor later changes to an entry a person posted from a rule placement, "
        "so this figure errs high.",
    )
    estimated_minutes_saved = serializers.IntegerField(
        help_text="rows_automated times assumed_minutes_per_row. An estimate, not a measurement: "
        "nothing records how long a person would have taken."
    )


class MetricsFirmSerializer(MetricFiguresSerializer):
    clients = serializers.IntegerField(help_text="Clients the caller may see; the totals cover these.")
    clients_needing_attention = serializers.IntegerField(help_text="Clients with at least one reason.")


class MetricsClientSerializer(MetricFiguresSerializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    needs_attention = AttentionReasonSerializer(many=True, help_text="Empty when nothing needs a look.")


class MetricsMemberSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The membership id.")
    name = serializers.CharField()


class MetricsTurnaroundSerializer(serializers.Serializer):
    member = MetricsMemberSerializer()
    statements_completed = serializers.IntegerField(
        help_text="Statements this person uploaded in the period whose every row has since been posted "
        "(or is the mirror of a transfer already posted)."
    )
    median_days_upload_to_posted = serializers.FloatField(
        allow_null=True,
        help_text="Median days from upload to the last row of the statement being posted. Null when none "
        "completed. Elapsed time, not working time.",
    )
    books_signed_off = serializers.IntegerField(
        help_text="Sign-offs this person made in the period for which a request for review was recorded."
    )
    median_days_request_to_sign_off = serializers.FloatField(
        allow_null=True,
        help_text="Median days from the latest request for review before the sign-off to the sign-off. "
        "Null when there were none.",
    )


class FirmMetricsSerializer(serializers.Serializer):
    period = MetricsPeriodSerializer()
    assumed_minutes_per_row = serializers.IntegerField(
        help_text="The minutes a person is assumed to need per row (setting ASSUMED_MINUTES_PER_ROW)."
    )
    is_estimate = serializers.BooleanField(
        help_text="Always true: estimated_minutes_saved is an assumption times a count."
    )
    firm = MetricsFirmSerializer()
    clients = MetricsClientSerializer(many=True)
    turnaround = MetricsTurnaroundSerializer(
        many=True, help_text="One entry per person with work in the period; sorted by name, not ranked."
    )
