"""Work counts for the dashboards: weekly flow, per-person counts, a member's own work. Counts of work, not ratings."""

from __future__ import annotations

from rest_framework import serializers

from api.serializers.metrics import MetricsPeriodSerializer
from core.models import Role


class WorkFlowWeekSerializer(serializers.Serializer):
    week_start = serializers.DateField(help_text="The Monday of the week.")
    received = serializers.IntegerField(
        help_text="Bank statement rows in statements uploaded in this week (inside the period)."
    )
    finished = serializers.IntegerField(
        help_text="Journal entries posted or approved in this week (inside the period), corrections not counted."
    )


class WorkFlowTotalsSerializer(serializers.Serializer):
    received = serializers.IntegerField(help_text="Rows received in the period.")
    finished = serializers.IntegerField(help_text="Entries finished in the period.")
    prev_received = serializers.IntegerField(
        help_text="Rows received in the period of equal length immediately before."
    )
    prev_finished = serializers.IntegerField(
        help_text="Entries finished in the period of equal length immediately before."
    )


class WorkFlowSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=["firm", "team"],
        help_text="What the figures cover: `firm` for a caller who sees every client, otherwise `team` (the clients they may see).",
    )
    period = MetricsPeriodSerializer()
    weekly = WorkFlowWeekSerializer(many=True)
    totals = WorkFlowTotalsSerializer()


class PersonWorkSerializer(serializers.Serializer):
    member_id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.ChoiceField(choices=Role.choices)
    assigned_clients = serializers.IntegerField(
        help_text="Clients the person is assigned to or leads, among those the caller may see."
    )
    open_items = serializers.IntegerField(
        help_text="Rows still to place + rows to post + assistant entries nobody has checked, on their clients. Right now."
    )
    finished_in_period = serializers.IntegerField(
        help_text="Entries the person approved or posted in the period, corrections not counted. Assistant entries are no one's."
    )
    overdue = serializers.IntegerField(
        help_text="Overdue alerts on their clients: TDS past its deposit date, or a sealing date passed unsealed. Right now."
    )
    waiting_on_others = serializers.IntegerField(
        help_text=(
            "On their clients: statement months missing (waiting on the client) plus books sent to a senior and "
            "not yet decided. Right now."
        )
    )


class PeopleWorkSerializer(serializers.Serializer):
    period = MetricsPeriodSerializer()
    detailed = serializers.BooleanField(
        help_text="False when more than 60 clients have someone on them: the per-client detail behind `overdue` is not worked out then, so it shows 0."
    )
    people = PersonWorkSerializer(many=True)


class DailyFinishedSerializer(serializers.Serializer):
    date = serializers.DateField()
    finished = serializers.IntegerField()


class NextTaskSerializer(serializers.Serializer):
    client = serializers.UUIDField()
    client_name = serializers.CharField()
    title = serializers.CharField(help_text="A few words: what is to be done.")
    due = serializers.DateField(
        allow_null=True, help_text="The date it was or falls due, where there is one."
    )
    to = serializers.CharField(help_text="The screen where this is done, as an app path.")
    search = serializers.DictField(
        child=serializers.CharField(), help_text="The query that screen needs."
    )
    severity = serializers.ChoiceField(choices=["critical", "high", "medium"])


class MyClientSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    open_items = serializers.IntegerField()


class MyWorkSerializer(serializers.Serializer):
    period = MetricsPeriodSerializer()
    assigned_clients = serializers.IntegerField(
        help_text="Clients the member is assigned to or leads."
    )
    open_items = serializers.IntegerField(
        help_text="Rows to place + rows to post + assistant entries unchecked, on their clients. Right now."
    )
    overdue = serializers.IntegerField(
        help_text="Overdue alerts on their clients (TDS past due, a sealing date passed). Right now."
    )
    waiting = serializers.IntegerField(
        help_text="Statement months missing plus books awaiting a senior's decision, on their clients. Right now."
    )
    finished_in_period = serializers.IntegerField(
        help_text="Entries this member approved or posted in the period."
    )
    daily = DailyFinishedSerializer(many=True, help_text="One row for every day of the period.")
    next_tasks = NextTaskSerializer(
        many=True, help_text="Up to 8, overdue first, then most serious, then earliest due."
    )
    clients = MyClientSerializer(many=True, help_text="Their clients, alphabetical.")
