"""Ledgers, parties, rules, and the review queue.

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
    Party,
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

    def validate_name(self, value: str) -> str:
        from classify.models import LedgerStatus

        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the ledger a name.")
        client = getattr(self.context.get("view"), "client", None)
        if client is None:
            return value
        # Tally keeps one ledger per name whatever the case, so "salary received" beside
        # "Salary Received" would split a year across two. The database's own uniqueness is
        # case-sensitive, so this is where that is refused.
        clash = LedgerAccount.objects.filter(client=client, name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        else:
            # A rejected or merely proposed ledger of this name is revived by creating it
            # (see LedgerAccountViewSet.perform_create), which is not a clash.
            clash = clash.filter(status=LedgerStatus.ACTIVE)
        existing = clash.first()
        if existing is not None:
            raise serializers.ValidationError(
                f'This client already has a ledger called "{existing.name}". Tally treats names that differ '
                "only in capital letters as the same ledger."
            )
        return value


class PartySerializer(serializers.ModelSerializer):
    gstin = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Stored encrypted, with a keyed index so GST reconciliation can join on it.",
    )

    class Meta:
        model = Party
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

    def validate_canonical_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the party a name.")
        client = getattr(self.context.get("view"), "client", None)
        if client is not None:
            clash = Party.objects.filter(client=client, canonical_name__iexact=value)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            existing = clash.first()
            if existing is not None:
                raise serializers.ValidationError(f'This client already has a party called "{existing.canonical_name}".')
        return value

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
        party = Party(**validated_data)
        party.set_gstin(gstin)
        party.save()
        return party

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
            "party",
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
        # ``client`` is set from the URL the rule was created under. Leaving it
        # writable would let a PATCH move one client's rule into another's book.
        read_only_fields = [
            "id",
            "client",
            "ledger_name",
            "source",
            "hit_count",
            "last_hit_at",
            "created_at",
        ]

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

        self._reject_another_clients_objects(attrs)
        return attrs

    def _reject_another_clients_objects(self, attrs):
        """A rule may not name a ledger or party belonging to a different client.

        ``ModelSerializer`` does not call ``Model.full_clean``, so the model's
        own ``clean`` never runs on this path and would not be reached until
        the database rejected the write. The rule's client comes from the URL
        on create, so the value to check against is the view's client, not
        anything the request may have put in the body.
        """
        client = getattr(self.context.get("view"), "client", None)
        if client is None:
            client = attrs.get("client") or getattr(self.instance, "client", None)
        if client is None:
            return

        errors = {}
        ledger = attrs.get("ledger") or getattr(self.instance, "ledger", None)
        if ledger is not None and ledger.client_id != client.pk:
            errors["ledger"] = "That ledger belongs to another client."
        party = attrs.get("party") or getattr(self.instance, "party", None)
        if party is not None and party.client_id != client.pk:
            errors["party"] = "That party belongs to another client."
        if errors:
            raise serializers.ValidationError(errors)


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
    party = serializers.UUIDField(
        required=False, allow_null=True, help_text="Party id, where there is an identifiable one."
    )
    rcm = serializers.BooleanField(
        default=False,
        help_text="Reverse charge: the client pays the GST rather than the party.",
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


class ConfirmPartySerializer(serializers.Serializer):
    party = serializers.UUIDField(help_text="The party this payee is.")


class ClassificationSerializer(serializers.ModelSerializer):
    """A row awaiting a decision, with everything needed to make it."""

    transaction = StatementTransactionSerializer(read_only=True)
    ledger_name = serializers.CharField(source="ledger.name", read_only=True, allow_null=True)
    ledger_status = serializers.CharField(source="ledger.status", read_only=True, allow_null=True)
    ledger_group = serializers.CharField(source="ledger.group", read_only=True, allow_null=True)
    ledger_group_display = serializers.CharField(
        source="ledger.get_group_display", read_only=True, allow_null=True
    )
    #: True for a ledger the model opened. Shown so the reviewer can rename it
    #: to the client's Tally spelling before month end.
    ledger_opened_by_model = serializers.SerializerMethodField()
    voucher_type = serializers.SerializerMethodField()
    entry_legs = serializers.SerializerMethodField()
    party_name = serializers.CharField(
        source="party.canonical_name", read_only=True, allow_null=True
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
            "ledger_group",
            "ledger_group_display",
            "ledger_opened_by_model",
            "voucher_type",
            "entry_legs",
            "book_narration",
            "open_question",
            "party",
            "party_name",
            "party_resolution",
            "party_candidates",
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
            "ai_revised",
            "reviewed_at",
        ]
        read_only_fields = fields

    def get_ledger_opened_by_model(self, obj) -> bool:
        return bool(obj.ledger and obj.ledger.proposal_reason)

    def get_entry_legs(self, obj) -> list[dict]:
        """Both sides of the entry this row makes, as a voucher shows them.

        Every transaction touches two accounts: the bank, and whatever the
        money was for. Money out debits the other ledger and credits the bank;
        money in is the reverse. ``ledger`` is null while the row is unplaced,
        and the leg is still listed so the entry is visibly incomplete rather
        than looking like a one-sided one.
        """
        from core.money import format_inr

        txn = obj.transaction
        amount = format_inr(txn.amount_paise)
        bank = {"ledger": txn.bank_account.ledger_name, "is_bank": True}
        other = {
            "ledger": obj.ledger.name if obj.ledger else None,
            "group": obj.ledger.get_group_display() if obj.ledger else None,
            "is_bank": False,
        }
        if txn.is_debit:
            legs = [{"side": "Dr", **other}, {"side": "Cr", **bank}]
        else:
            legs = [{"side": "Dr", **bank}, {"side": "Cr", **other}]
        return [{**leg, "amount_display": amount} for leg in legs]

    def get_voucher_type(self, obj) -> str | None:
        if obj.ledger is None:
            return None
        from ledger.approval import voucher_type_for

        return voucher_type_for(obj)

    def get_is_posted(self, obj) -> bool:
        if obj.mirrored_entry_id:
            return True
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
    also_revised = serializers.IntegerField(
        read_only=True,
        help_text=(
            "How many entries or rows the AI had placed itself that the new rule "
            "moved. Never includes anything a person decided."
        ),
    )
    auto_posted = serializers.IntegerField(
        read_only=True,
        help_text="How many rows became certain enough to be posted automatically.",
    )
