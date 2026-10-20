"""Who is asking, which firm they are in, and what they may do."""

from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import serializers

from core.access import can_post, can_sign_off
from core.identifiers import is_valid_cin, is_valid_pan, is_valid_tan, is_valid_udyam
from core.models import CLIENT_IDENTIFIERS, Client, Constitution, Firm, Job, JobStatus
from core.rbac import PERMISSIONS, has_permission


class FirmSerializer(serializers.ModelSerializer):
    class Meta:
        model = Firm
        fields = ["id", "name", "is_active", "created_at"]
        read_only_fields = fields


class ClientSerializer(serializers.ModelSerializer):
    #: Who leads the client. Set on the Team page, never through this endpoint.
    lead = serializers.SerializerMethodField()
    #: Whether the signed-in member may approve and correct this client's
    #: entries. Presentation only; ledger.approval checks again.
    can_sign_off = serializers.SerializerMethodField()
    can_post = serializers.SerializerMethodField()
    #: Whether any entry is posted for this client. The same fact that locks ``fy_start``.
    has_entries = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id", "name", "fy_start", "business_profile", "created_at", "lead", "can_sign_off", "can_post",
            "has_entries", "close_period",
        ]
        read_only_fields = ["id", "created_at", "lead", "can_sign_off", "can_post", "has_entries"]
        extra_kwargs = {
            "fy_start": {
                "help_text": "First day of the client's financial year: always 1 April.",
            },
            "close_period": {
                "help_text": "How often the books are sealed: QUARTERLY, HALF_YEARLY or YEARLY. A senior's approval locks nothing; the seal does.",
            },
            "business_profile": {
                "help_text": "What the client's business does, in a few sentences. Shown to the model that suggests ledgers.",
                "required": False,
                "max_length": 2000,
            },
        }

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Give the client a name.")
        request = self.context.get("request")
        firm_id = getattr(getattr(request, "firm", None), "pk", None)
        clash = Client.objects.filter(firm_id=firm_id, name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if firm_id and clash.exists():
            raise serializers.ValidationError("The firm already has a client with this name.")
        return value

    def validate_business_profile(self, value: str) -> str:
        return value.strip()

    def validate_fy_start(self, value):
        unchanged = self.instance is not None and value == self.instance.fy_start
        if (value.month, value.day) != (4, 1) and not unchanged:
            raise serializers.ValidationError(
                "The financial year starts on 1 April. Books here always run April to March."
            )
        if self.instance is not None and value != self.instance.fy_start:
            from ledger.models import JournalEntry

            if JournalEntry.objects.filter(client=self.instance).exists():
                raise serializers.ValidationError(
                    "This client already has posted entries, which are numbered by financial year. "
                    "The financial year start can't change now."
                )
        return value

    def get_lead(self, client) -> dict | None:
        lead = client.lead
        if lead is None:
            return None
        return {"id": str(lead.pk), "name": lead.user.full_name or lead.user.email}

    def get_has_entries(self, client) -> bool:
        flag = getattr(client, "has_entries_flag", None)
        if flag is not None:
            return flag
        from ledger.models import JournalEntry

        return JournalEntry.objects.filter(client=client).exists()

    def get_can_post(self, client) -> bool:
        request = self.context.get("request")
        return can_post(getattr(request, "membership", None), client)

    def get_can_sign_off(self, client) -> bool:
        request = self.context.get("request")
        return can_sign_off(getattr(request, "membership", None), client)


def _mask(value: str) -> str:
    """ABCDE1234F becomes AB*******F: enough to recognise, not enough to use."""
    return value if len(value) < 4 else value[:2] + "*" * (len(value) - 3) + value[-1]


class ClientProfileSerializer(serializers.ModelSerializer):
    """Who the client is: registrations, contacts, notes.

    The registration numbers are kept encrypted. A person who may edit the profile sees them in full; anyone else who
    can open the client sees them masked. None of this is sent to the model tier.
    """

    name = serializers.CharField(read_only=True)
    pan = serializers.CharField(required=False, allow_blank=True, max_length=10)
    tan = serializers.CharField(required=False, allow_blank=True, max_length=10)
    cin = serializers.CharField(required=False, allow_blank=True, max_length=21)
    udyam = serializers.CharField(required=False, allow_blank=True, max_length=24)
    #: Other clients of the firm (that the caller can see) filed under the same PAN: usually a mistake worth a look.
    pan_shared_with = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id", "name", "trade_name", "constitution", "incorporated_on", "client_since", "address",
            "contact_name", "contact_email", "contact_phone",
            "contact2_name", "contact2_email", "contact2_phone",
            "msme_category", "notes", "pan", "tan", "cin", "udyam",
            "pan_shared_with", "can_edit", "profile_updated_at", "profile_updated_by",
        ]
        read_only_fields = ["id", "profile_updated_at", "profile_updated_by"]

    def _may_edit(self) -> bool:
        return has_permission(getattr(self.context.get("request"), "membership", None), "client.profile")

    def get_can_edit(self, client) -> bool:
        return self._may_edit()

    def get_pan_shared_with(self, client) -> list[str]:
        if not client.pan_hash:
            return []
        from core.access import visible_clients

        request = self.context.get("request")
        mine = visible_clients(request.membership).values("pk")
        others = Client.objects.filter(firm_id=client.firm_id, pan_hash=client.pan_hash, pk__in=mine).exclude(pk=client.pk)
        return list(others.values_list("name", flat=True))

    def to_representation(self, client):
        data = super().to_representation(client)
        editable = self._may_edit()
        for kind in CLIENT_IDENTIFIERS:
            value = client.identifier(kind)
            data[kind] = value if editable else _mask(value)
        return data

    def validate_pan(self, value: str) -> str:
        value = value.strip().upper()
        if value and not is_valid_pan(value):
            raise serializers.ValidationError("A PAN is ten characters, like ABCPE1234F.")
        return value

    def validate_tan(self, value: str) -> str:
        value = value.strip().upper()
        if value and not is_valid_tan(value):
            raise serializers.ValidationError("A TAN is ten characters, like ABCD12345E.")
        return value

    def validate_cin(self, value: str) -> str:
        value = value.strip().upper()
        if value and not is_valid_cin(value):
            raise serializers.ValidationError("Enter a company's 21-character CIN (U12345MH2020PTC123456) or an LLP's LLPIN (AAB-1234).")
        return value

    def validate_udyam(self, value: str) -> str:
        value = value.strip().upper()
        if value and not is_valid_udyam(value):
            raise serializers.ValidationError("A Udyam number looks like UDYAM-MH-12-1234567.")
        return value

    def validate(self, attrs):
        entity = attrs.get("constitution", getattr(self.instance, "constitution", ""))
        cin = attrs.get("cin", self.instance.identifier("cin") if self.instance else "")
        if cin:
            is_llpin = "-" in cin
            if entity == Constitution.LLP and not is_llpin:
                raise serializers.ValidationError({"cin": "An LLP has an LLPIN, like AAB-1234, not a company CIN."})
            if entity in (Constitution.PRIVATE_LIMITED, Constitution.PUBLIC_LIMITED) and is_llpin:
                raise serializers.ValidationError({"cin": "A company has a 21-character CIN, not an LLPIN."})
        if (when := attrs.get("incorporated_on")) and when > datetime.date.today():
            raise serializers.ValidationError({"incorporated_on": "That date has not happened yet."})
        for field in ("contact_name", "contact2_name", "trade_name"):
            if field in attrs:
                attrs[field] = attrs[field].strip()
        return attrs

    def update(self, instance, validated_data):
        for kind in CLIENT_IDENTIFIERS:
            if kind in validated_data:
                instance.set_identifier(kind, validated_data.pop(kind))
        for field, value in validated_data.items():
            setattr(instance, field, value)
        user = getattr(self.context.get("request"), "user", None)
        instance.profile_updated_at = timezone.now()
        instance.profile_updated_by = (getattr(user, "full_name", "") or getattr(user, "email", "")) if user else ""
        instance.save()
        return instance


class MeSerializer(serializers.Serializer):
    """The session, the firm it is bound to, and the permissions it carries.

    The permission list is sent so a client can hide what it must not offer.
    That is presentation only -- every one of them is checked again server-side,
    because a hidden button is not a permission system.
    """

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    firm = FirmSerializer(read_only=True, allow_null=True)
    membership_id = serializers.UUIDField(read_only=True, allow_null=True)
    role = serializers.CharField(read_only=True, allow_null=True)
    role_display = serializers.CharField(read_only=True, allow_null=True)
    is_owner = serializers.BooleanField(read_only=True)
    permissions = serializers.ListField(child=serializers.CharField(), read_only=True)

    @classmethod
    def for_request(cls, request) -> dict:
        membership = getattr(request, "membership", None)
        user = request.user
        return {
            "id": user.pk,
            "email": user.email,
            "full_name": user.full_name,
            "firm": getattr(request, "firm", None),
            "membership_id": membership.pk if membership else None,
            "role": membership.role if membership else None,
            "role_display": (
                ("Firm owner" if membership.is_owner else membership.get_role_display())
                if membership
                else None
            ),
            "is_owner": bool(membership and membership.is_owner),
            "permissions": sorted(PERMISSIONS.get(membership.role, set())) if membership else [],
        }


class JobSerializer(serializers.ModelSerializer):
    """What a 202 hands back, and what polling returns.

    ``result`` is whatever the work produced -- its shape depends on ``kind``
    and is documented on the endpoint that starts the job.

    A job waiting in the queue also says how many are ahead of it in the firm (approximate: others finish or arrive between polls, so it is
    not a time) and whether a reader process is looking at the queue, which is how a screen can tell "waiting its turn" from "nobody is reading".
    """

    queue_ahead = serializers.SerializerMethodField(help_text="Jobs of this kind in the firm queued before this one and not yet finished; null unless waiting.")
    reader_running = serializers.SerializerMethodField(help_text="Whether a reader process is looking at the queue; null unless waiting.")

    class Meta:
        model = Job
        fields = [
            "id",
            "kind",
            "status",
            "progress",
            "message",
            "result",
            "error",
            "error_code",
            "created_at",
            "started_at",
            "finished_at",
            "queue_ahead",
            "reader_running",
        ]
        read_only_fields = fields

    def get_queue_ahead(self, job) -> int | None:
        if job.status != JobStatus.PENDING:
            return None
        return (
            Job.objects.filter(firm_id=job.firm_id, kind=job.kind, created_at__lt=job.created_at)
            .exclude(status__in=JobStatus.terminal())
            .count()
        )

    def get_reader_running(self, job) -> bool | None:
        if job.status != JobStatus.PENDING:
            return None
        from core import jobqueue

        return jobqueue.reader_running()
