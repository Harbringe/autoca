"""What the team, firm and owner endpoints answer, described for the API schema.

These views build plain dicts, so without this the generated schema calls every reply
"an object" and the web app types it by hand. Nothing here runs at request time: the
serializers only describe, and each ``extend_schema`` decorator is applied to a view
method in ``teams/views.py``.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers

from core.models import Role


class PersonSerializer(serializers.Serializer):
    """A member of the firm, as named beside a client or in a list.

    The owner appears like anyone else, to every role that can see the team. Only the owner
    can change the owner (by transferring ownership); anyone else gets 403.
    """

    id = serializers.CharField(help_text="The membership id.")
    name = serializers.CharField()
    role = serializers.ChoiceField(choices=Role.choices)
    role_display = serializers.CharField()
    is_owner = serializers.BooleanField()
    is_active = serializers.BooleanField()


class PeriodSerializer(serializers.Serializer):
    # `from` is a keyword, so the schema field is declared through the class dict below.
    to = serializers.DateField()


PeriodSerializer._declared_fields["from"] = serializers.DateField()


class MetricSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    note = serializers.CharField(help_text="How to read the number where its label alone would mislead. Often empty.")


class WorkTotalsSerializer(serializers.Serializer):
    """Counts of work in the period, one per metric in `metrics`. Keys are the metric keys."""

    statements_uploaded = serializers.IntegerField()
    rows_placed = serializers.IntegerField()
    entries_approved = serializers.IntegerField(help_text="First-time approvals, not corrections.")
    entries_corrected = serializers.IntegerField()
    entries_posted = serializers.IntegerField(
        help_text=(
            "Entries carrying this person's name: approvals and corrections together. "
            "Entries the assistant posted by itself are counted for nobody."
        )
    )
    books_sent_for_review = serializers.IntegerField(help_text="Times this person asked a senior to sign a client's books off.")
    ledgers_created = serializers.IntegerField()
    rules_written = serializers.IntegerField()
    proposals_decided = serializers.IntegerField()
    model_runs = serializers.IntegerField()


class MemberClientSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    how = serializers.CharField(help_text="`assigned` or `leads`.")


class MemberCanSerializer(serializers.Serializer):
    manage = serializers.BooleanField(help_text="May change this person's role and reporting line.")
    manage_role = serializers.BooleanField()
    set_active = serializers.BooleanField(help_text="May deactivate or reactivate this person.")


class MemberSerializer(PersonSerializer):
    user_id = serializers.CharField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    scope_all_clients = serializers.BooleanField()
    manager = PersonSerializer(
        allow_null=True,
        help_text=(
            "Who this person reports to: owner -> administrators -> Senior CAs -> Staff and "
            "Read-only. Null for the owner."
        ),
    )
    last_login = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    is_me = serializers.BooleanField()
    clients = MemberClientSerializer(many=True)
    can = MemberCanSerializer()


class MemberWithWorkSerializer(MemberSerializer):
    work = WorkTotalsSerializer()


class MembersCanSerializer(serializers.Serializer):
    invite = serializers.BooleanField()
    invite_roles = serializers.ListField(child=serializers.CharField(), help_text="Roles the person asking may invite.")
    role_options = serializers.ListField(child=serializers.CharField(), help_text="Roles the person asking may give.")
    manage = serializers.BooleanField()
    manage_admins = serializers.BooleanField(help_text="May invite administrators and hand ownership on: the owner only.")


class MembersResponseSerializer(serializers.Serializer):
    period = PeriodSerializer()
    metrics = MetricSerializer(many=True)
    can = MembersCanSerializer()
    leads = PersonSerializer(many=True, help_text="Active Senior CAs and administrators who can be named as a client's lead or a manager.")
    results = MemberWithWorkSerializer(many=True)


class InviteRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    role = serializers.ChoiceField(choices=Role.choices)
    role_display = serializers.CharField()
    manager = PersonSerializer(allow_null=True)
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    created_by = serializers.EmailField(allow_null=True)


class InviteCreatedSerializer(InviteRecordSerializer):
    link = serializers.CharField(help_text="The one-time link to send the person. Shown only now.")


class InvitesResponseSerializer(serializers.Serializer):
    results = InviteRecordSerializer(many=True)


class ByClientSerializer(WorkTotalsSerializer):
    id = serializers.CharField(allow_null=True, help_text="Null for work not tied to a client.")
    name = serializers.CharField()


class ByDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField()


class BookToSendSerializer(serializers.Serializer):
    unresolved = serializers.IntegerField(help_text="Rows nobody has placed in a ledger yet.")
    pending_approval = serializers.IntegerField(help_text="Rows placed but not yet posted.")
    books_to_send = serializers.BooleanField(
        help_text=(
            "True when every row is placed and posted, nothing is already waiting for a senior, and "
            "there are entries newer than the last sign-off: the books can be sent for review now."
        )
    )


class OpenWorkSerializer(BookToSendSerializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MemberWorkResponseSerializer(serializers.Serializer):
    member = PersonSerializer()
    period = PeriodSerializer()
    metrics = MetricSerializer(many=True)
    totals = WorkTotalsSerializer()
    by_client = ByClientSerializer(many=True)
    by_day = ByDaySerializer(many=True)
    open_work = OpenWorkSerializer(many=True, help_text="What is waiting now on the clients this person can see, not history.")


class AssignedPersonSerializer(PersonSerializer):
    assigned_at = serializers.DateTimeField()
    on_my_team = serializers.BooleanField(help_text="Reports directly to the person asking.")


class TeamClientSerializer(BookToSendSerializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    lead = PersonSerializer(allow_null=True)
    team = AssignedPersonSerializer(many=True)


class TeamClientsCanSerializer(serializers.Serializer):
    set_lead = serializers.BooleanField()


class TeamClientsResponseSerializer(serializers.Serializer):
    can = TeamClientsCanSerializer()
    assignable = PersonSerializer(many=True, help_text="Who the person asking may put on a client.")
    results = TeamClientSerializer(many=True)


class LeadSetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    lead = PersonSerializer(allow_null=True)


class AssignedSerializer(serializers.Serializer):
    assigned = PersonSerializer()


class TeamEventDetailSerializer(serializers.Serializer):
    """What a team event records. Names are as they were then; which keys appear depends on `kind`.

    | kind | keys |
    |---|---|
    | member.invited | actor, email, role, to (the manager, or empty) |
    | member.joined | actor, member, role |
    | invite.revoked | actor, email |
    | member.role_changed | actor, member, from, to |
    | member.manager_changed | actor, member, from, to, removed_from_clients |
    | member.scope_changed | actor, member, to (`on` or `off`) |
    | member.deactivated, member.reactivated | actor, member |
    | member.removed | actor, member, role |
    | client.lead_changed | actor, client, from, to |
    | client.assigned, client.unassigned | actor, member, client |
    | firm.owner_changed | actor, member, from, to |
    | firm.renamed | actor, from, to |

    `actor` is "AutoCA platform" for a change made by the platform owner.
    """

    actor = serializers.CharField(required=False)
    member = serializers.CharField(required=False)
    client = serializers.CharField(required=False)
    email = serializers.CharField(required=False)
    role = serializers.CharField(required=False)
    to = serializers.CharField(required=False)
    removed_from_clients = serializers.IntegerField(required=False)


TeamEventDetailSerializer._declared_fields["from"] = serializers.CharField(required=False)


class TeamEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField(help_text="One of the `kind` values in the table on `detail`.")
    kind_display = serializers.CharField()
    detail = TeamEventDetailSerializer()
    member_id = serializers.UUIDField(allow_null=True)
    client_id = serializers.UUIDField(allow_null=True)
    at = serializers.DateTimeField()


class TeamEventsResponseSerializer(serializers.Serializer):
    results = TeamEventSerializer(many=True, help_text="The latest 200, newest first.")


class FirmCountsSerializer(serializers.Serializer):
    active_members = serializers.IntegerField()
    senior_cas = serializers.IntegerField()
    staff = serializers.IntegerField()
    clients = serializers.IntegerField()


class FirmCanSerializer(serializers.Serializer):
    rename = serializers.BooleanField()
    transfer = serializers.BooleanField(help_text="May hand ownership to another administrator: the owner only.")


class FirmResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField()
    owner = PersonSerializer(allow_null=True)
    admins = PersonSerializer(many=True, help_text="Active administrators; the owner is left out for an administrator who is not the owner.")
    counts = FirmCountsSerializer()
    can = FirmCanSerializer()


class FirmRenamedSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class OwnerTransferredSerializer(serializers.Serializer):
    owner = PersonSerializer()


# -- the decorators, applied in views.py -----------------------------------------

_TEAM = ["team"]

members_get = extend_schema(
    tags=_TEAM,
    summary="The team, with each person's work in a period",
    parameters=[
        OpenApiParameter("from", OpenApiTypes.DATE, description="Start of the period. Defaults to 30 days ago."),
        OpenApiParameter("to", OpenApiTypes.DATE, description="End of the period, inclusive. Defaults to today."),
    ],
    responses={200: MembersResponseSerializer},
)


def members_post(request):
    return extend_schema(
        request=request, tags=_TEAM, summary="Invite someone", responses={201: InviteCreatedSerializer}
    )


member_get = extend_schema(tags=_TEAM, summary="One member", responses={200: MemberSerializer})


def member_patch(request):
    return extend_schema(
        request=request,
        tags=_TEAM,
        summary="Change a member's role, reporting line, access or active state",
        responses={200: MemberSerializer},
    )


member_work_get = extend_schema(
    tags=_TEAM,
    summary="One person's work in a period, and what is waiting on them now",
    parameters=[
        OpenApiParameter("from", OpenApiTypes.DATE, description="Start of the period. Defaults to 30 days ago."),
        OpenApiParameter("to", OpenApiTypes.DATE, description="End of the period, inclusive. Defaults to today."),
    ],
    responses={200: MemberWorkResponseSerializer},
)
clients_get = extend_schema(
    tags=_TEAM, summary="Clients with their lead, team and open work", responses={200: TeamClientsResponseSerializer}
)


def client_lead_put(request):
    return extend_schema(
        request=request,
        tags=_TEAM,
        summary="Set or clear a client's lead",
        responses={200: LeadSetSerializer},
    )


def client_team_post(request):
    return extend_schema(
        request=request,
        tags=_TEAM,
        summary="Put someone on a client",
        responses={201: AssignedSerializer},
    )


client_team_delete = extend_schema(
    tags=_TEAM,
    summary="Take someone off a client",
    responses={204: None},
)
invites_get = extend_schema(tags=_TEAM, summary="Invitations still open", responses={200: InvitesResponseSerializer})
invite_delete = extend_schema(tags=_TEAM, summary="Revoke an invitation", responses={204: None})
events_get = extend_schema(
    tags=_TEAM, summary="Who changed the team, and how", responses={200: TeamEventsResponseSerializer}
)
firm_get = extend_schema(
    tags=["firm"], summary="The firm, its owner and administrators", responses={200: FirmResponseSerializer}
)


def firm_patch(request):
    return extend_schema(
        request=request, tags=["firm"], summary="Rename the firm", responses={200: FirmRenamedSerializer}
    )


def firm_owner_post(request):
    return extend_schema(
        request=request,
        tags=["firm"],
        summary="Hand ownership to another administrator",
        responses={200: OwnerTransferredSerializer},
    )
