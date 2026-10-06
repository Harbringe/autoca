"""Who is asking, which firm they are in, and what they may do."""

from __future__ import annotations

from rest_framework import serializers

from core.access import can_post, can_sign_off
from core.models import Client, Firm, Job
from core.rbac import PERMISSIONS


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
    """

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
        ]
        read_only_fields = fields
