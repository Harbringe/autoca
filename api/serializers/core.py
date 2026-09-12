"""Who is asking, which firm they are in, and what they may do."""

from __future__ import annotations

from rest_framework import serializers

from core.models import Client, Firm, Job
from core.rbac import PERMISSIONS


class FirmSerializer(serializers.ModelSerializer):
    class Meta:
        model = Firm
        fields = ["id", "name", "is_active", "created_at"]
        read_only_fields = fields


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ["id", "name", "fy_start", "created_at"]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {
            "fy_start": {
                "help_text": "First day of the client's financial year, normally 1 April.",
            }
        }


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
    role = serializers.CharField(read_only=True, allow_null=True)
    role_display = serializers.CharField(read_only=True, allow_null=True)
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
            "role": membership.role if membership else None,
            "role_display": membership.get_role_display() if membership else None,
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
