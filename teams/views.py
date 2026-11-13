"""The team API (``/api/v1/team/``) and invite acceptance (``/auth/invite/``)."""

from __future__ import annotations

import datetime
import json
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import Throttled as ApiThrottled
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from core import throttle
from core.access import visible_clients
from core.db.session import TenantContextError, firm_context
from core.http import client_ip
from core.models import Client, ClientAssignment, Firm, FirmMembership, Role, User
from teams import activity, mail, schemas, service
from teams.models import Invite, TeamEventKind, hash_token

security_log = logging.getLogger("autoca.security")


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def _person(membership: FirmMembership | None) -> dict | None:
    if membership is None:
        return None
    return {
        "id": str(membership.pk),
        "name": service.label(membership),
        "role": membership.role,
        "role_display": service.role_label(membership),
        "is_owner": membership.is_owner,
        "is_active": membership.is_active,
    }


def _member(actor: FirmMembership, m: FirmMembership, clients_by_member: dict) -> dict:
    admin = service.is_admin(actor)
    own_team = service.is_lead(actor) and m.manager_id == actor.pk
    # Administrators are the owner's to manage; the owner is nobody's.
    admin_ok = m.role != Role.FIRM_ADMIN or service.can_manage_admins(actor)
    untouchable = m.is_owner or m.pk == actor.pk
    manage_role = not untouchable and (
        (admin and admin_ok) or (own_team and m.role in service.TEAM_ROLES)
    )
    return {
        **_person(m),
        "user_id": str(m.user_id),
        "email": m.user.email,
        "full_name": m.user.full_name,
        "scope_all_clients": m.scope_all_clients or m.role == Role.FIRM_ADMIN,
        "manager": _person(m.manager),
        "last_login": m.user.last_login,
        "created_at": m.created_at,
        "is_me": m.pk == actor.pk,
        "clients": clients_by_member.get(m.pk, []),
        "can": {
            "manage": admin and admin_ok and not untouchable,
            "manage_role": manage_role,
            "set_active": (admin and admin_ok or own_team) and not untouchable,
        },
    }


def _clients_by_member(members) -> dict:
    """{membership_id: [{"id", "name", "how"}]} -- assigned, or leads."""
    ids = [m.pk for m in members]
    out: dict = {pk: [] for pk in ids}
    for a in ClientAssignment.objects.filter(membership_id__in=ids).select_related("client"):
        out[a.membership_id].append({"id": str(a.client_id), "name": a.client.name, "how": "assigned"})
    for c in Client.objects.filter(lead_id__in=ids):
        out[c.lead_id].append({"id": str(c.pk), "name": c.name, "how": "leads"})
    for items in out.values():
        items.sort(key=lambda item: item["name"].lower())
    return out


def _period(request) -> activity.Period:
    tz = timezone.get_current_timezone()
    today = timezone.localdate()

    def parse(name, fallback):
        raw = request.query_params.get(name)
        if not raw:
            return fallback
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError as exc:
            raise serializers.ValidationError({name: "Use YYYY-MM-DD."}) from exc

    start = parse("from", today - datetime.timedelta(days=29))
    end = parse("to", today)
    if end < start:
        raise serializers.ValidationError({"to": "The end date is before the start date."})
    if (end - start).days > 366:
        raise serializers.ValidationError({"from": "Pick a period of a year or less."})
    return activity.Period(
        start=datetime.datetime.combine(start, datetime.time.min, tzinfo=tz),
        end=datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz),
    )


def _membership_or_404(actor, pk) -> FirmMembership:
    member = service.visible_members(actor).filter(pk=pk).first()
    if member is None:
        raise Http404("No such person.")
    return member


def _any_member(actor, pk) -> FirmMembership:
    """Any member of the firm, for naming a new manager or an assignee."""
    member = FirmMembership.objects.filter(firm_id=actor.firm_id, pk=pk).select_related("user").first()
    if member is None:
        raise serializers.ValidationError({"member": "No such person in this firm."})
    return member


def _managed_client_or_404(actor, pk) -> Client:
    client = service.managed_clients(actor).filter(pk=pk).first()
    if client is None:
        raise Http404("No such client.")
    return client


class TeamView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "team.view"


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    role = serializers.ChoiceField(choices=Role.choices, default=Role.STAFF)
    manager = serializers.UUIDField(required=False, allow_null=True)


class BulkInviteSerializer(serializers.Serializer):
    rows = serializers.ListField(child=InviteSerializer(), min_length=1, max_length=50, help_text="Up to 50 people.")


class BulkInviteRowSerializer(serializers.Serializer):
    email = serializers.CharField()
    ok = serializers.BooleanField()
    error = serializers.CharField(required=False, help_text="Why this row was not invited.")
    link = serializers.CharField(required=False)
    emailed = serializers.BooleanField(required=False)
    role_display = serializers.CharField(required=False)
    expires_at = serializers.DateTimeField(required=False)


class BulkInviteResultSerializer(serializers.Serializer):
    results = BulkInviteRowSerializer(many=True)


class MemberUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices, required=False)
    manager = serializers.UUIDField(required=False, allow_null=True)
    scope_all_clients = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    keep_client_assignments = serializers.BooleanField(required=False, default=False)


class MembersView(TeamView):
    required_permission = {"GET": "team.view", "POST": "member.invite"}

    @schemas.members_get
    def get(self, request):
        actor = request.membership
        members = list(service.visible_members(actor).order_by("-is_active", "role", "user__email"))
        by_member = _clients_by_member(members)
        period = _period(request)
        work = activity.work_by_user(actor.firm_id, [m.user_id for m in members], period)
        leads = FirmMembership.objects.filter(
            firm_id=actor.firm_id, is_active=True, role__in=service.LEAD_ROLES
        )
        return Response(
            {
                "period": {"from": period.start.date(), "to": (period.end - datetime.timedelta(days=1)).date()},
                "metrics": activity.metric_list(),
                "can": {
                    "invite": True,
                    "invite_roles": (
                        [r for r in Role.values if r != Role.FIRM_ADMIN or service.can_manage_admins(actor)]
                        if service.is_admin(actor)
                        else sorted(service.TEAM_ROLES)
                    ),
                    "role_options": list(Role.values) if service.is_admin(actor) else sorted(service.TEAM_ROLES),
                    "manage": service.is_admin(actor),
                    "manage_admins": service.can_manage_admins(actor),
                },
                "leads": [
                    _person(m)
                    for m in leads.select_related("user")
                ],
                "results": [
                    {**_member(actor, m, by_member), "work": work[m.user_id].totals} for m in members
                ],
            }
        )

    @schemas.members_post(InviteSerializer)
    def post(self, request):
        payload = InviteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        record, url, emailed = _issue_invite(request, data)
        return Response({**_invite(record), "link": url, "emailed": emailed}, status=201)


class MemberView(TeamView):
    required_permission = {"GET": "team.view", "PATCH": "team.view"}

    @schemas.member_get
    def get(self, request, pk):
        actor = request.membership
        member = _membership_or_404(actor, pk)
        return Response(_member(actor, member, _clients_by_member([member])))

    @schemas.member_patch(MemberUpdateSerializer)
    def patch(self, request, pk):
        actor = request.membership
        member = _membership_or_404(actor, pk)
        payload = MemberUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        manager = ...
        if "manager" in data:
            manager = _any_member(actor, data["manager"]) if data["manager"] else None
        updated = service.update_member(
            actor,
            member,
            role=data.get("role"),
            manager=manager,
            scope_all_clients=data.get("scope_all_clients"),
            is_active=data.get("is_active"),
            keep_client_assignments=data["keep_client_assignments"],
        )
        updated = FirmMembership.objects.select_related("user", "manager__user").get(pk=updated.pk)
        return Response(_member(actor, updated, _clients_by_member([updated])))


class MemberWorkView(APIView):
    """One person's work. Anyone may see their own; leads and admins their team's."""

    permission_classes = [HasFirmPermission]
    required_permission = "client.view"

    @schemas.member_work_get
    def get(self, request, pk):
        actor = request.membership
        member = _membership_or_404(actor, pk)
        period = _period(request)
        report = activity.work_by_user(actor.firm_id, [member.user_id], period)[member.user_id]
        names = activity.client_names(actor.firm_id, report.by_client.keys())
        clients = list(visible_clients(member)) if member.is_active else []
        open_work = activity.open_work(clients)
        days = []
        day = period.start.date()
        while day < period.end.date():
            days.append({"date": day, "count": report.by_day.get(day.isoformat(), 0)})
            day += datetime.timedelta(days=1)
        return Response(
            {
                "member": _person(member),
                "period": {"from": period.start.date(), "to": (period.end - datetime.timedelta(days=1)).date()},
                "metrics": activity.metric_list(),
                "totals": report.totals,
                "by_client": sorted(
                    (
                        {"id": str(cid) if cid else None, "name": names.get(cid, "Deleted client"), **counts}
                        for cid, counts in report.by_client.items()
                    ),
                    key=lambda row: row["name"].lower(),
                ),
                "by_day": days,
                "open_work": [
                    {"id": str(c.pk), "name": c.name, **open_work[c.pk]}
                    for c in sorted(clients, key=lambda c: c.name.lower())
                ],
            }
        )


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


class LeadSerializer(serializers.Serializer):
    lead = serializers.UUIDField(allow_null=True)


class AssignSerializer(serializers.Serializer):
    member = serializers.UUIDField()


class ClientsView(TeamView):
    @schemas.clients_get
    def get(self, request):
        actor = request.membership
        clients = list(
            service.managed_clients(actor)
            .annotate(team_size=Count("assignments"))
            .order_by("name")
        )
        assignments: dict = {c.pk: [] for c in clients}
        for a in ClientAssignment.objects.filter(client__in=clients).select_related("membership__user"):
            assignments[a.client_id].append(
                {**_person(a.membership), "assigned_at": a.created_at, "on_my_team": a.membership.manager_id == actor.pk}
            )
        open_work = activity.open_work(clients)
        assignable = FirmMembership.objects.filter(firm_id=actor.firm_id, is_active=True).exclude(
            role=Role.FIRM_ADMIN
        )
        if not service.is_admin(actor):
            assignable = assignable.filter(manager=actor)
        return Response(
            {
                "can": {"set_lead": service.is_admin(actor)},
                "assignable": [_person(m) for m in assignable.select_related("user")],
                "results": [
                    {
                        "id": str(c.pk),
                        "name": c.name,
                        "lead": _person(c.lead),
                        "team": sorted(assignments[c.pk], key=lambda p: p["name"].lower()),
                        **open_work[c.pk],
                    }
                    for c in clients
                ],
            }
        )


class ClientLeadView(TeamView):
    required_permission = "member.manage"

    @schemas.client_lead_put(LeadSerializer)
    def put(self, request, pk):
        actor = request.membership
        client = _managed_client_or_404(actor, pk)
        payload = LeadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lead_id = payload.validated_data["lead"]
        lead = _any_member(actor, lead_id) if lead_id else None
        service.set_lead(actor, client, lead)
        return Response({"id": str(client.pk), "lead": _person(lead)})


class ClientTeamView(TeamView):
    required_permission = "team.assign"

    @schemas.client_team_post(AssignSerializer)
    def post(self, request, pk):
        actor = request.membership
        client = _managed_client_or_404(actor, pk)
        payload = AssignSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        member = _any_member(actor, payload.validated_data["member"])
        service.assign(actor, client, member)
        return Response({"assigned": _person(member)}, status=201)

    @schemas.client_team_delete
    def delete(self, request, pk, member_id):
        actor = request.membership
        client = _managed_client_or_404(actor, pk)
        member = _any_member(actor, member_id)
        service.unassign(actor, client, member)
        return Response(status=204)


# ---------------------------------------------------------------------------
# Invites and history
# ---------------------------------------------------------------------------


def _issue_invite(request, data) -> tuple[Invite, str, bool]:
    """One invitation, with the limits on making them. Returns the record, the link, and whether it was also emailed.

    The link goes to the person who sends it (there is no email unless the platform has been set up for it), so an invitation is a way
    to try an address and a password against the whole platform. Making them is limited per sender and per address, and a bulk
    request counts every row.
    """
    actor = request.membership
    manager = _any_member(actor, data["manager"]) if data.get("manager") else None
    issuer, target = str(request.user.pk), data["email"].strip().lower()
    try:
        throttle.check("invite_create", issuer)
        throttle.check("invite_target", target)
    except throttle.Throttled as exc:
        raise ApiThrottled(wait=exc.retry_after) from exc
    record, link = service.invite(
        actor,
        email=data["email"],
        full_name=data.get("full_name", ""),
        role=data["role"],
        manager=manager,
    )
    throttle.record_failure("invite_create", issuer)
    throttle.record_failure("invite_target", target)
    return record, *_deliver(request, record, link)


def _deliver(request, record: Invite, link: str) -> tuple[str, bool]:
    """The link as a URL, and an attempt to email it (which does nothing unless emailing has been switched on)."""
    url = f"{settings.FRONTEND_URL}/invite/{link}"
    actor = request.membership
    emailed = mail.send_invite(
        to=record.email,
        firm_name=Firm.objects.get(pk=actor.firm_id).name,
        inviter=service.label(actor),
        role="Firm owner" if record.make_owner else Role(record.role).label,
        url=url,
        expires_days=max((record.expires_at - timezone.now()).days, 1),
    )
    return url, emailed


def _status(record: Invite) -> str:
    left = record.expires_at - timezone.now()
    if left <= datetime.timedelta(0):
        return "expired"
    return "expiring_soon" if left < datetime.timedelta(hours=48) else "pending"


def _invite(record: Invite) -> dict:
    return {
        "id": str(record.pk),
        "email": record.email,
        "full_name": record.full_name,
        "role": record.role,
        "role_display": Role(record.role).label,
        "manager": _person(record.manager),
        "expires_at": record.expires_at,
        "status": _status(record),
        "created_at": record.created_at,
        "created_by": getattr(record.created_by, "email", None),
    }


class InvitesView(TeamView):
    required_permission = "member.invite"

    @schemas.invites_get
    def get(self, request):
        # Expired ones stay listed for a month, so they can be replaced with a new link instead of being forgotten.
        invites = service.visible_invites(request.membership).filter(expires_at__gt=timezone.now() - datetime.timedelta(days=30))
        return Response({"results": [_invite(i) for i in invites]})


class InviteView(TeamView):
    required_permission = "member.invite"

    @schemas.invite_delete
    def delete(self, request, pk):
        record = service.visible_invites(request.membership).filter(pk=pk).first()
        if record is None:
            raise Http404("No such invite.")
        service.revoke_invite(request.membership, record)
        return Response(status=204)


class MembersBulkView(TeamView):
    required_permission = "member.invite"

    @extend_schema(
        tags=["team"],
        summary="Invite several people at once",
        description=(
            "Up to 50 rows. Each is checked and limited like a single invitation; one that cannot be made says why and the others "
            "still go. Every link is shown only in this response."
        ),
        request=BulkInviteSerializer,
        responses={200: BulkInviteResultSerializer},
    )
    def post(self, request):
        payload = BulkInviteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        results = []
        for row in payload.validated_data["rows"]:
            try:
                with transaction.atomic():
                    record, url, emailed = _issue_invite(request, row)
            except ApiThrottled:
                results.append({"email": row["email"], "ok": False, "error": "Too many invitations just now. Try again in a while."})
            except service.TeamError as exc:
                results.append({"email": row["email"], "ok": False, "error": "; ".join(exc.messages)})
            except (PermissionDenied, Http404) as exc:
                results.append({"email": row["email"], "ok": False, "error": str(exc) or "Not allowed."})
            except (ValidationError, serializers.ValidationError) as exc:
                results.append({"email": row["email"], "ok": False, "error": "; ".join(getattr(exc, "messages", None) or [str(exc)])})
            else:
                results.append(
                    {
                        "email": record.email,
                        "ok": True,
                        "link": url,
                        "emailed": emailed,
                        "role_display": Role(record.role).label,
                        "expires_at": record.expires_at,
                    }
                )
        return Response({"results": results})


class InviteRegenerateView(TeamView):
    required_permission = "member.invite"

    @extend_schema(
        tags=["team"],
        summary="Replace an invitation's link",
        description="The secret in a link is never stored, so a lost link cannot be shown again: this makes a new one and the old one stops working.",
        request=None,
        responses={201: schemas.InviteCreatedSerializer},
    )
    def post(self, request, pk):
        record = service.visible_invites(request.membership).filter(pk=pk).first()
        if record is None:
            raise Http404("No such invite.")
        fresh, link = service.regenerate_invite(request.membership, record)
        url, emailed = _deliver(request, fresh, link)
        return Response({**_invite(fresh), "link": url, "emailed": emailed}, status=201)


class InviteExtendView(TeamView):
    required_permission = "member.invite"

    @extend_schema(
        tags=["team"],
        summary="Give an invitation another week",
        description="Adds seven days, never going past thirty days after the invitation was made.",
        request=None,
        responses={200: schemas.InviteRecordSerializer},
    )
    def post(self, request, pk):
        record = service.visible_invites(request.membership).filter(pk=pk).first()
        if record is None:
            raise Http404("No such invite.")
        return Response(_invite(service.extend_invite(request.membership, record)))


class EventsView(TeamView):
    @schemas.events_get
    def get(self, request):
        events = service.visible_events(request.membership)[:200]
        labels = dict(TeamEventKind.choices)
        return Response(
            {
                "results": [
                    {
                        "id": str(e.pk),
                        "kind": e.kind,
                        "kind_display": labels.get(e.kind, e.kind),
                        "detail": e.detail,
                        "member_id": str(e.member_id) if e.member_id else None,
                        "client_id": str(e.client_id) if e.client_id else None,
                        "at": e.created_at,
                    }
                    for e in events
                ]
            }
        )


# ---------------------------------------------------------------------------
# Firm settings
# ---------------------------------------------------------------------------


class FirmSettingsSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)


class OwnerSerializer(serializers.Serializer):
    member = serializers.UUIDField()


class FirmSettingsView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "firm.manage", "PATCH": "firm.manage"}

    @schemas.firm_get
    def get(self, request):
        actor = request.membership
        firm = Firm.objects.get(pk=actor.firm_id)
        members = FirmMembership.objects.filter(firm_id=actor.firm_id).select_related("user")
        owner = next((m for m in members if m.is_owner), None)
        return Response(
            {
                "id": str(firm.pk),
                "name": firm.name,
                "created_at": firm.created_at,
                "owner": _person(owner),
                "admins": [_person(m) for m in members if m.role == Role.FIRM_ADMIN and m.is_active],
                "counts": {
                    "active_members": sum(1 for m in members if m.is_active),
                    "senior_cas": sum(1 for m in members if m.is_active and m.role == Role.SENIOR_CA),
                    "staff": sum(1 for m in members if m.is_active and m.role in service.TEAM_ROLES),
                    "clients": Client.objects.filter(firm_id=actor.firm_id).count(),
                },
                "can": {
                    "rename": True,
                    "transfer": service.can_manage_admins(actor),
                },
            }
        )

    @schemas.firm_patch(FirmSettingsSerializer)
    def patch(self, request):
        payload = FirmSettingsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        firm = service.rename_firm(request.membership, payload.validated_data["name"])
        return Response({"id": str(firm.pk), "name": firm.name})


class FirmOwnerView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "firm.manage"

    @schemas.firm_owner_post(OwnerSerializer)
    def post(self, request):
        actor = request.membership
        payload = OwnerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        new_owner = _any_member(actor, payload.validated_data["member"])
        service.transfer_ownership(actor, new_owner)
        return Response({"owner": _person(FirmMembership.objects.select_related("user").get(pk=new_owner.pk))})


# ---------------------------------------------------------------------------
# Accepting an invite (no session yet)
# ---------------------------------------------------------------------------


def _json_error(code: str, detail: str, status: int) -> JsonResponse:
    return JsonResponse({"code": code, "detail": detail}, status=status)


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


def _throttled_response(exc: throttle.Throttled) -> JsonResponse:
    response = _json_error(
        "too_many_attempts", f"Too many attempts. Try again in {max(exc.retry_after // 60, 1)} minutes.", 429
    )
    response["Retry-After"] = str(exc.retry_after)
    return response


_INVALID = "This invite link isn't valid. Ask for a new one."


def _describe(token: str) -> JsonResponse:
    """What an invite is for. It says nothing about whether the address already has an account: whoever holds the link may be the one
    who made it, and could otherwise use it to learn who has an account on the platform."""
    parts = service.split_link(token)
    if parts is None:
        return _json_error("invalid_invite", _INVALID, 404)
    firm_id, secret = parts
    throttle_key = hash_token(secret)
    try:
        throttle.check("invite", throttle_key)
    except throttle.Throttled as exc:
        return _throttled_response(exc)
    try:
        with transaction.atomic(), firm_context(firm_id):
            record = service.find_invite(secret)
            problem = service.invite_problem(record)
            if problem:
                throttle.record_failure("invite", throttle_key)
                return _json_error("invalid_invite", problem, 410 if record else 404)
            firm = Firm.objects.get(pk=record.firm_id)
            return JsonResponse(
                {
                    "email": record.email,
                    "full_name": record.full_name,
                    "firm": firm.name,
                    "role_display": "Firm owner" if record.make_owner else Role(record.role).label,
                    "team": service.label(record.manager) if record.manager else "",
                }
            )
    except TenantContextError:
        return _json_error("invalid_invite", _INVALID, 404)


@require_http_methods(["POST"])
def describe_invite(request):
    """POST {token} describes the invite. The token travels in the body, not the URL: a URL is written to access logs, browser history
    and Referer headers, and the token is a credential."""
    return _describe(str(_body(request).get("token", ""))[:200])


@require_http_methods(["GET", "POST"])
def accept_invite(request):
    """POST {token, full_name, password} redeems an invite; GET ?token= describes it (kept for links already in use).

    The token carries the firm id so the lookup can run under that firm's
    tenant context before anyone is signed in. Throttled on the token itself,
    and, when the address already has an account, on the sign-in counters too.
    Redeeming signs the person in with a password only; the MFA middleware then
    sends them to enrol an authenticator before anything else.
    """
    if request.method == "GET":
        return _describe(str(request.GET.get("token", ""))[:200])

    data = _body(request)
    token = str(data.get("token", ""))[:200]
    parts = service.split_link(token)
    if parts is None:
        return _json_error("invalid_invite", _INVALID, 404)
    firm_id, secret = parts
    throttle_key = hash_token(secret)
    address = client_ip(request) or ""

    try:
        throttle.check("invite", throttle_key)
    except throttle.Throttled as exc:
        return _throttled_response(exc)

    try:
        with transaction.atomic(), firm_context(firm_id):
            record = service.find_invite(secret)
            problem = service.invite_problem(record)
            if problem:
                throttle.record_failure("invite", throttle_key)
                return _json_error("invalid_invite", problem, 410 if record else 404)

            existing = User.objects.filter(email=record.email).first()
            password = str(data.get("password", ""))
            if existing is not None:
                # A password is being tried against an account anywhere on the platform, so it counts against that account and that
                # address like any sign-in, not only against this one invite (which a sender can replace at will).
                try:
                    throttle.sign_in_check(address, existing.email)
                except throttle.Throttled as exc:
                    security_log.warning("invite sign-in refused (locked out) ip=%s", address)
                    return _throttled_response(exc)
                # A platform owner or staff account is never attached to a firm by an invite; it answers as a wrong password does.
                if existing.is_superuser or existing.is_staff or authenticate(request, username=existing.email, password=password) is None:
                    throttle.record_failure("invite", throttle_key)
                    throttle.sign_in_failed(address, existing.email)
                    return _json_error("invalid_credentials", "That isn't the password for this account.", 401)
            try:
                membership = service.accept(
                    record,
                    full_name=str(data.get("full_name", ""))[:255],
                    password=password,
                    existing_user=existing,
                )
            except service.TeamError as exc:
                return _json_error("team_rule", "; ".join(exc.messages), 409)
            except ValidationError as exc:  # the password validators
                return JsonResponse(
                    {
                        "code": "invalid",
                        "detail": "Choose a stronger password.",
                        "fields": {"password": exc.messages},
                    },
                    status=400,
                )
            user = membership.user
    except TenantContextError:
        return _json_error("invalid_invite", _INVALID, 404)

    user.backend = settings.AUTHENTICATION_BACKENDS[0]
    login(request, user)
    security_log.info("invite accepted user=%s firm=%s", user.pk, firm_id)
    return JsonResponse(
        {"detail": "You're in. Set up your authenticator next.", "mfa": "verify" if user.has_mfa else "setup"}
    )
