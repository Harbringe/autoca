"""Ledgers, vendors, rules, and the review queue.

The review queue is the screen this API exists to make possible, so its
serializer carries everything a reviewer needs to decide without a second
request: the transaction as the bank printed it, what was read out of the
narration, how confident the system is and on what basis.
"""

from __future__ import annotations

import re

from rest_framework import serializers

from api.serializers.banking import StatementTransactionSerializer
from classify.models import (
    ClassificationRule,
    LedgerAccount,
    LedgerGroup,
    MatchType,
    TransactionClassification,
    Vendor,
)
from classify.treatment import ReviewBand, TdsSection
from core.identifiers import is_valid_gstin

#: A quantifier applied to a group that itself contains a quantifier --
#: ``(a+)+``, ``(\w*)*`` -- is the shape that makes a regex engine backtrack
#: exponentially. A rule is evaluated against every row of every statement, so
#: one such pattern from one member of staff would stall the firm's uploads.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")
MAX_RULE_PATTERN_LENGTH = 200


class LedgerAccountSerializer(serializers.ModelSerializer):
    is_bank_or_cash = serializers.BooleanField(read_only=True)
    row_count = serializers.IntegerField(
        read_only=True, default=0, help_text="Classifications currently placed in this ledger."
    )

    class Meta:
        model = LedgerAccount
        fields = [
            "id", "name", "group", "is_bank_or_cash", "is_active",
            "status", "proposal_reason", "row_count", "created_at",
        ]
        read_only_fields = ["id", "is_bank_or_cash", "status", "proposal_reason", "row_count", "created_at"]
        extra_kwargs = {
            "name": {
                "help_text": (
                    "Must match the ledger name in the client's Tally company exactly. "
                    "Tally creates an unrecognised name rather than rejecting it, so a "
                    "near-miss silently splits a year across two ledgers."
                )
            }
        }


class VendorSerializer(serializers.ModelSerializer):
    gstin = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Stored encrypted, with a keyed index so GST reconciliation can join on it.",
    )

    class Meta:
        model = Vendor
        fields = [
            "id",
            "canonical_name",
            "alias_token",
            "gstin",
            "rcm_default",
            "tds_section",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "alias_token", "created_at"]

    def validate_gstin(self, value):
        value = (value or "").strip().upper()
        if value and not is_valid_gstin(value):
            raise serializers.ValidationError(
                "Not a valid GSTIN. Fifteen characters: state code, PAN, entity "
                "number, Z, check character."
            )
        return value

    def create(self, validated_data):
        gstin = validated_data.pop("gstin", "")
        vendor = Vendor(**validated_data)
        vendor.set_gstin(gstin)
        vendor.save()
        return vendor

    def update(self, instance, validated_data):
        if "gstin" in validated_data:
            instance.set_gstin(validated_data.pop("gstin"))
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance


class ClassificationRuleSerializer(serializers.ModelSerializer):
    ledger_name = serializers.CharField(source="ledger.name", read_only=True)

    class Meta:
        model = ClassificationRule
        fields = [
            "id",
            "client",
            "ledger",
            "ledger_name",
            "vendor",
            "rcm",
            "tds_section",
            "match_type",
            "pattern",
            "direction",
            "priority",
            "confidence",
            "source",
            "is_active",
            "hit_count",
            "last_hit_at",
            "created_at",
        ]
        read_only_fields = ["id", "ledger_name", "source", "hit_count", "last_hit_at", "created_at"]

    def validate(self, attrs):
        match_type = attrs.get("match_type", getattr(self.instance, "match_type", None))
        pattern = attrs.get("pattern", getattr(self.instance, "pattern", ""))
        if len(pattern) > MAX_RULE_PATTERN_LENGTH:
            raise serializers.ValidationError(
                {"pattern": f"At most {MAX_RULE_PATTERN_LENGTH} characters."}
            )
        if match_type == MatchType.REGEX:
            if _NESTED_QUANTIFIER.search(pattern):
                raise serializers.ValidationError(
                    {
                        "pattern": (
                            "A repeated group containing a repetition -- like (a+)+ -- can "
                            "take the matcher exponential time. Rewrite without nesting."
                        )
                    }
                )
            try:
                re.compile(pattern)
            except re.error as exc:
                raise serializers.ValidationError({"pattern": f"Not a valid regex: {exc}"}) from exc
        return attrs


class AcceptProposalSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False, max_length=255, help_text="Rename to match the client's Tally company exactly."
    )
    group = serializers.ChoiceField(choices=LedgerGroup.choices, required=False)


class MergeProposalSerializer(serializers.Serializer):
    into = serializers.UUIDField(help_text="An existing, in-use ledger of the same client.")


class RecategorizeSerializer(serializers.Serializer):
    statement = serializers.UUIDField(required=False, allow_null=True)


class TreatmentSerializer(serializers.Serializer):
    """One complete accounting decision: where it goes, who it was with, and its tax.

    All four together, because they are decided together and learned together.
    A rule that remembered the ledger and forgot the reverse-charge flag would
    look like it worked until a return was prepared from incomplete books.
    """

    ledger = serializers.UUIDField(help_text="Ledger account id.")
    vendor = serializers.UUIDField(
        required=False, allow_null=True, help_text="Party id, where there is an identifiable one."
    )
    rcm = serializers.BooleanField(
        default=False,
        help_text="Reverse charge: the client pays the GST rather than the vendor.",
    )
    tds_section = serializers.ChoiceField(
        choices=TdsSection.CHOICES,
        required=False,
        allow_blank=True,
        default="",
        help_text="TDS section, if the payment type crosses its threshold.",
    )
    learn = serializers.BooleanField(
        default=True,
        help_text=(
            "Teach a rule from this decision so the same payee is placed "
            "automatically from now on. Set false for a genuine one-off."
        ),
    )


class ClassificationSerializer(serializers.ModelSerializer):
    """A row awaiting a decision, with everything needed to make it."""

    transaction = StatementTransactionSerializer(read_only=True)
    ledger_name = serializers.CharField(source="ledger.name", read_only=True, allow_null=True)
    ledger_status = serializers.CharField(source="ledger.status", read_only=True, allow_null=True)
    vendor_name = serializers.CharField(
        source="vendor.canonical_name", read_only=True, allow_null=True
    )
    is_posted = serializers.SerializerMethodField()
    method_display = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = TransactionClassification
        fields = [
            "id",
            "transaction",
            "ledger",
            "ledger_name",
            "ledger_status",
            "vendor",
            "vendor_name",
            "rcm",
            "tds_section",
            "method",
            "method_display",
            "rationale",
            "confidence",
            "review_band",
            "needs_review",
            "channel",
            "counterparty",
            "is_self_transfer",
            "is_posted",
            "reviewed_at",
        ]
        read_only_fields = fields

    def get_is_posted(self, obj) -> bool:
        return any(not entry.is_superseded for entry in obj.transaction.journal_entries.all())


class ReviewSummarySerializer(serializers.Serializer):
    """How much work is waiting, split by how much thought each row needs.

    The ordering is the feature: it is what turns an hour of checking every row
    into minutes of checking the ones that need it.
    """

    high = serializers.IntegerField(help_text="High confidence. Eligible for bulk approval.")
    advised = serializers.IntegerField(help_text="Suggested, but worth a look.")
    judgement = serializers.IntegerField(help_text="No suggestion. Needs a person.")
    total = serializers.IntegerField()
    bulk_approvable = serializers.IntegerField()
    unresolved = serializers.IntegerField(help_text="Of the total, how many have no ledger yet.")
    pending_approval = serializers.IntegerField(
        help_text="Of the total, how many have a ledger and await a senior CA."
    )


class ApproveSerializer(serializers.Serializer):
    """Post reviewed rows to the immutable journal.

    Either an explicit list of classification ids, or a whole confidence band --
    the latter is the one-click bulk approval the review screen offers for
    everything the system is sure about.
    """

    classifications = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False
    )
    band = serializers.ChoiceField(
        choices=[ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT], required=False
    )

    def validate(self, attrs):
        if bool(attrs.get("classifications")) == bool(attrs.get("band")):
            raise serializers.ValidationError(
                "Send either a list of classifications or a band, and not both."
            )
        return attrs


class PlacementResultSerializer(serializers.Serializer):
    """What changed when a row was placed."""

    classification = ClassificationSerializer(read_only=True)
    rule_learned = serializers.UUIDField(read_only=True, allow_null=True)
    also_placed = serializers.IntegerField(
        read_only=True,
        help_text="How many other queued rows the rule learned from this decision placed.",
    )
