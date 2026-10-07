"""Ledgers, parties, rules, and the review queue.

The review queue is the screen this API exists to make possible, so its
serializer carries everything a reviewer needs to decide without a second
request: the transaction as the bank printed it, what was read out of the
narration, how confident the system is and on what basis.
"""

from __future__ import annotations

import re

from rest_framework import serializers

from api.fields import PaiseField
from api.serializers.banking import StatementTransactionSerializer
from api.serializers.settlement import RowSettlementSerializer
from classify import regex_guard
from classify.models import (
    ClassificationRule,
    LedgerAccount,
    LedgerGroup,
    MatchType,
    Party,
    TransactionClassification,
)
from classify.treatment import ReviewBand, TdsSection
from core.fy import financial_year
from core.identifiers import is_valid_gstin
from core.money import format_inr

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
                    "The ledger's name in this client's books. Unique per client, ignoring "
                    "case and spacing: \"Advance Tax\" and \"Advance tax\" would split a year "
                    "across two ledgers, so the second is refused."
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
        # One ledger per name whatever the case, so "salary received" beside
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
                f'This client already has a ledger called "{existing.name}". Names that differ '
                "only in capital letters as the same ledger, and two would split the books."
            )
        return value

    def validate(self, attrs):
        """What a ledger is cannot be changed once the books rest on it.

        Reports read a ledger's group live, so regrouping a ledger that has entries would change signed-off figures with
        no entry and no lock. A bank account finds its ledger by name, and a party's account is tied to the party, so
        neither is renamed or regrouped here. (A bank ledger is renamed with its account; the Tally import applies the
        same rule to groups.)
        """
        ledger = self.instance
        if ledger is None:
            return attrs
        from banking.models import BankAccount
        from ledger.models import JournalLine

        regroup = "group" in attrs and attrs["group"] != ledger.group
        rename = "name" in attrs and attrs["name"] != ledger.name
        if not (regroup or rename):
            return attrs
        if ledger.is_party_account:
            raise serializers.ValidationError(
                "This is a party's own account. Change it through the party; its name and group follow the party."
            )
        if BankAccount.objects.filter(client_id=ledger.client_id, ledger_name=ledger.name).exists():
            raise serializers.ValidationError(
                "This is a bank account's ledger. Rename it from the bank account, which moves its entries with it."
            )
        if regroup and JournalLine.objects.filter(ledger_account=ledger).exists():
            raise serializers.ValidationError(
                {"group": "Entries are already posted to this ledger, so its group cannot change. "
                          "Post a journal entry to move the balance instead."}
            )
        return attrs


class PartySerializer(serializers.ModelSerializer):
    gstin = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Stored encrypted, with a keyed index so GST reconciliation can join on it.",
    )
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    ledger_name = serializers.CharField(source="ledger.name", read_only=True, default=None)

    class Meta:
        model = Party
        fields = [
            "id",
            "canonical_name",
            "role",
            "role_display",
            "ledger",
            "ledger_name",
            "alias_token",
            "gstin",
            "rcm_default",
            "tds_section",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "ledger", "alias_token", "created_at"]

    def validate_role(self, value):
        """A supplier cannot become a customer under bills already booked to it: they would be on the wrong side."""
        if self.instance is not None and value != self.instance.role and self.instance.bills.exists():
            raise serializers.ValidationError(
                "This party already has bills, so its role cannot change. Book the other side under a new party."
            )
        return value

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
            try:
                regex_guard.check(pattern)
            except regex_guard.UnsafeRegex as exc:
                raise serializers.ValidationError({"pattern": str(exc)}) from exc
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
        required=False, max_length=255, help_text="Rename the ledger as it is accepted, e.g. to the spelling the client already uses."
    )
    group = serializers.ChoiceField(choices=LedgerGroup.choices, required=False)


class MergeProposalSerializer(serializers.Serializer):
    into = serializers.UUIDField(help_text="An existing, in-use ledger of the same client.")


class RecategorizeSerializer(serializers.Serializer):
    statement = serializers.UUIDField(required=False, allow_null=True)


class NextBatchRequestSerializer(serializers.Serializer):
    max_rows = serializers.IntegerField(
        required=False, min_value=1, max_value=15, help_text="How many waiting rows to read. Defaults to 10, at most 15."
    )


class NextBatchSerializer(serializers.Serializer):
    """What one call to the assistant did, and what to do next."""

    processed = serializers.IntegerField(help_text="Rows this call asked the model about.")
    suggested = serializers.IntegerField(help_text="Of those, rows the model placed in a ledger.")
    declined = serializers.IntegerField(help_text="Rows left for a person.")
    waiting = serializers.IntegerField(help_text="Rows still waiting for the assistant, including any another window is reading.")
    state = serializers.ChoiceField(
        choices=["working", "idle", "paused"],
        help_text="`working`: call again. `idle`: nothing is waiting, or the assistant is off; stop. `paused`: call again after `retry_after_seconds`.",
    )
    retry_after_seconds = serializers.IntegerField(allow_null=True, help_text="When to call again. Null when the call may be repeated straight away.")
    reason = serializers.ChoiceField(
        choices=["", "rate_limit", "daily_limit", "provider_down", "assistant_off"],
        help_text="Why the assistant is paused or idle. Blank when it is working.",
    )
    message = serializers.CharField(help_text="One plain sentence to show.")
    auto_posted = serializers.IntegerField(help_text="Of the suggested rows, how many were sure enough to be posted automatically.")
    proposed = serializers.IntegerField(help_text="New ledgers the assistant opened in this call.")


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
    on_party_account = serializers.SerializerMethodField()

    class Meta:
        model = TransactionClassification
        fields = [
            "id",
            "transaction",
            "on_party_account",
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

    def get_on_party_account(self, obj) -> bool:
        """True when the row is placed on a supplier's or customer's own account.

        Such a row cannot be approved without saying which bills it settles, and is never approved with a whole band.
        """
        return bool(obj.ledger and obj.ledger.is_party_account)

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
        return row_is_posted(obj)


def row_is_posted(obj) -> bool:
    """True when the row has a live entry in the books.

    A row whose entries were all corrected since counts as unposted; a mirrored row shows
    the entry its twin on the other account wrote. Callers listing many rows prefetch
    ``transaction__journal_entries__superseded_by_set`` so this costs no query per row.
    """
    if obj.mirrored_entry_id:
        return True
    return any(not entry.is_superseded for entry in obj.transaction.journal_entries.all())


class LedgerRowSerializer(serializers.ModelSerializer):
    """A row placed in a ledger, and whether it has reached the books yet.

    The ledger list counts every row placed in it, but the books only hold what has been
    posted, in one financial year at a time. This is the list that reconciles the two.
    """

    transaction = serializers.UUIDField(source="transaction_id", read_only=True)
    value_date = serializers.DateField(source="transaction.value_date", read_only=True)
    financial_year = serializers.SerializerMethodField()
    narration = serializers.CharField(source="transaction.narration", read_only=True)
    amount_paise = PaiseField(source="transaction.amount_paise", read_only=True)
    amount_display = serializers.SerializerMethodField(help_text="The amount with Indian digit grouping, e.g. ₹6,03,490.57.")
    is_debit = serializers.BooleanField(source="transaction.is_debit", read_only=True)
    is_posted = serializers.SerializerMethodField()
    method_display = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = TransactionClassification
        fields = [
            "id",
            "transaction",
            "value_date",
            "financial_year",
            "narration",
            "book_narration",
            "counterparty",
            "amount_paise",
            "amount_display",
            "is_debit",
            "is_posted",
            "needs_review",
            "method",
            "method_display",
        ]
        read_only_fields = fields

    def get_financial_year(self, obj) -> int:
        return financial_year(obj.transaction.value_date)

    def get_amount_display(self, obj) -> str:
        return format_inr(obj.transaction.amount_paise)

    def get_is_posted(self, obj) -> bool:
        return row_is_posted(obj)


class ReviewSummarySerializer(serializers.Serializer):
    """How much work is waiting, split by how much thought each row needs.

    The ordering is the feature: it is what turns an hour of checking every row
    into minutes of checking the ones that need it.
    """

    high = serializers.IntegerField(help_text="High confidence. Eligible for bulk approval.")
    advised = serializers.IntegerField(help_text="Suggested, but worth a look.")
    judgement = serializers.IntegerField(help_text="No suggestion. Needs a person.")
    total = serializers.IntegerField()
    bulk_approvable = serializers.IntegerField(
        help_text="How many a whole-band approval would post: the high band, less rows on a party's account."
    )
    needs_settlement = serializers.IntegerField(
        help_text="Waiting rows placed on a supplier's or customer's own account. Each needs a person to say which bills it settles."
    )
    unresolved = serializers.IntegerField(help_text="Of the total, how many have no ledger yet.")
    pending_approval = serializers.IntegerField(
        help_text="Of the total, how many have a ledger and await a senior CA."
    )
    assistant_waiting = serializers.IntegerField(
        help_text="Rows queued for the assistant that it has not finished with. A background worker reads them; nobody needs a page open."
    )
    assistant_reason = serializers.ChoiceField(
        choices=["", "rate_limit", "daily_limit", "provider_down", "assistant_off"],
        help_text="Why the assistant is not reading right now. Blank when it is working or has nothing to do.",
    )
    assistant_retry_seconds = serializers.IntegerField(
        allow_null=True, help_text="When it reads again, for a pause. Null otherwise."
    )


class ApproveSerializer(serializers.Serializer):
    """Post reviewed rows to the immutable journal.

    Either an explicit list of classification ids, or a whole confidence band --
    the latter is the one-click bulk approval the review screen offers for
    everything the system is sure about.
    """

    classifications = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False, max_length=5000
    )
    band = serializers.ChoiceField(
        choices=[ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT], required=False
    )
    settlements = RowSettlementSerializer(
        many=True, required=False, max_length=500,
        help_text=(
            "For each row placed on a supplier's or customer's own account: which of the party's bills it pays, or "
            "whether it is held on account or as an advance. Such a row is refused without one, and is never approved "
            "as part of a whole band."
        ),
    )

    def validate(self, attrs):
        if bool(attrs.get("classifications")) == bool(attrs.get("band")):
            raise serializers.ValidationError(
                "Send exactly one of classifications or band."
            )
        if attrs.get("band") and attrs.get("settlements"):
            raise serializers.ValidationError(
                {"settlements": "Settlements go with a list of rows. A whole band never includes a party's account."}
            )
        return attrs


class PlacementResultSerializer(serializers.Serializer):
    """What changed when a row was placed."""

    classification = ClassificationSerializer(read_only=True)
    rule_learned = serializers.UUIDField(read_only=True, allow_null=True)
    rule_created = serializers.BooleanField(
        read_only=True,
        help_text="True when this decision wrote a new rule, false when it reused or updated one.",
    )
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
