"""Bills: purchase and sales invoices, and the credit and debit notes that reverse them.

Money is whole paise with a ``*_display`` string beside it, like everywhere else on this API. Posting a bill is a domain
operation (``ledger.billing``) with a permission to check, a voucher number to allocate under a lock and rules about
what an invoice may post to, so the create serializer only checks the shape of the request; the rules live in the domain
and their messages are passed through as they were written.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.fields import MoneySerializerMixin, PaiseField
from api.serializers.ledger import JournalLineSerializer
from classify.treatment import TdsSection
from core.identifiers import is_valid_gstin
from ledger.models import Bill, BillAllocation, BillKind

#: What a person can post. An opening balance is imported, never typed as a voucher.
POSTABLE_KINDS = [BillKind.PURCHASE, BillKind.SALES, BillKind.DEBIT_NOTE, BillKind.CREDIT_NOTE]

MONEY = (
    "taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "cess_paise",
    "round_off_paise", "tds_paise", "total_paise", "open_paise",
)


class AllocationSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = ("amount_paise",)

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    entry_no = serializers.IntegerField(source="line.entry.entry_no", read_only=True)
    voucher_type = serializers.CharField(source="line.entry.voucher_type", read_only=True)
    entry_date = serializers.DateField(source="line.entry.entry_date", read_only=True)

    class Meta:
        model = BillAllocation
        fields = ["id", "kind", "kind_display", "amount_paise", "line", "entry_no", "voucher_type", "entry_date"]
        read_only_fields = fields


class BillSerializer(MoneySerializerMixin, serializers.ModelSerializer):
    money = MONEY

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    party_name = serializers.CharField(source="party.canonical_name", read_only=True)
    voucher_type = serializers.CharField(source="entry.voucher_type", read_only=True, default=None)
    entry_no = serializers.IntegerField(source="entry.entry_no", read_only=True, default=None)
    has_document = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    open_paise = PaiseField(
        read_only=True,
        help_text="What is still unsettled: the total less everything allocated to it. Computed, never stored.",
    )

    class Meta:
        model = Bill
        fields = [
            "id", "kind", "kind_display", "direction",
            "party", "party_name",
            "reference", "bill_date", "due_date", "booked_on", "financial_year",
            "taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "cess_paise",
            "round_off_paise", "tds_paise", "rcm", "total_paise", "open_paise",
            "entry", "voucher_type", "entry_no",
            "document", "has_document", "is_locked", "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_has_document(self, obj) -> bool:
        # A file attached from the invoice side (``InvoiceReading``) counts: a bill is never edited to carry it.
        return obj.document_id is not None or hasattr(obj, "reading")

    @extend_schema_field(serializers.BooleanField())
    def get_is_locked(self, obj) -> bool:
        """Inside books a senior has signed off, so it can no longer be removed."""
        through = getattr(obj.client, "signed_off_through", None)
        return through is not None and obj.booked_on <= through


class BillDetailSerializer(BillSerializer):
    """The bill with the voucher it booked and everything that has settled it."""

    lines = JournalLineSerializer(source="entry.lines", many=True, read_only=True, default=[])
    allocations = AllocationSerializer(many=True, read_only=True)
    narration = serializers.CharField(source="entry.narration", read_only=True, default="")

    class Meta(BillSerializer.Meta):
        fields = [*BillSerializer.Meta.fields, "narration", "lines", "allocations"]
        read_only_fields = fields


class HeadSerializer(serializers.Serializer):
    ledger = serializers.UUIDField(help_text="An expense, purchase, sales or asset ledger of this client.")
    amount_paise = PaiseField(min_value=1, help_text="The taxable value that goes to this ledger.")


class ConfirmedLineSerializer(serializers.Serializer):
    """A line of the invoice as a person left it: kept so the next invoice from this party can be filled in the same way."""

    description = serializers.CharField(max_length=200)
    read_description = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    hsn_sac = serializers.CharField(max_length=8, required=False, allow_blank=True, default="")
    quantity = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    rate_paise = PaiseField(required=False, allow_null=True, default=None)
    amount_paise = PaiseField(required=False, allow_null=True, default=None)
    gst_rate = serializers.FloatField(required=False, allow_null=True, default=None, min_value=0, max_value=100)


class BillCreateSerializer(serializers.Serializer):
    """The shape of a voucher request. The accounting rules are the domain's, and say why in words."""

    kind = serializers.ChoiceField(choices=[(kind.value, kind.label) for kind in POSTABLE_KINDS])
    party = serializers.UUIDField()
    reference = serializers.CharField(max_length=64, help_text="The invoice or note number printed on the document.")
    bill_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True, default=None)
    heads = HeadSerializer(many=True, allow_empty=False)

    cgst_paise = PaiseField(required=False, default=0, min_value=0)
    sgst_paise = PaiseField(required=False, default=0, min_value=0)
    igst_paise = PaiseField(required=False, default=0, min_value=0)
    cess_paise = PaiseField(required=False, default=0, min_value=0)
    round_off_paise = PaiseField(
        required=False, default=0, help_text="Signed: positive when the invoice rounds up, negative when down."
    )
    tds_paise = PaiseField(
        required=False, default=0, min_value=0,
        help_text="Deducted when the bill is booked, so the supplier is owed the net. Purchases only.",
    )
    tds_section = serializers.ChoiceField(choices=TdsSection.CHOICES, required=False, allow_blank=True, default="")
    rcm = serializers.BooleanField(
        required=False, default=False,
        help_text="Reverse charge: the client, not the supplier, owes the GST. Purchases only.",
    )
    paid_from = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text=(
            "A cash ledger, or a bank ledger with no uploaded statements: the bill is paid in full when booked and the payment "
            "voucher is booked with it. Purchases and sales only; ignored when a bill is revised."
        ),
    )
    narration = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    own_gstin = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="The client's own GSTIN this belongs to, so it lands in the right return.",
    )
    document = serializers.UUIDField(required=False, allow_null=True, default=None, help_text="An uploaded invoice file.")
    itemwise = serializers.BooleanField(
        required=False, default=False,
        help_text=(
            "Post each invoice line to a purchase or sales ledger of its own and keep each product as a stock item. "
            "Needs every line to carry an amount and the lines to add up to the taxable value."
        ),
    )
    items = ConfirmedLineSerializer(
        many=True, required=False, default=list, max_length=100,
        help_text="The invoice's lines as the person left them. Kept with the invoice, to fill the party's next invoice.",
    )

    def validate_reference(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the invoice number.")
        return value

    def validate_own_gstin(self, value: str) -> str:
        value = (value or "").strip().upper()
        if value and not is_valid_gstin(value):
            raise serializers.ValidationError("Not a valid GSTIN.")
        return value


class RemoveBillSerializer(serializers.Serializer):
    release_payments = serializers.BooleanField(
        required=False, default=False,
        help_text="Also undo the payments settled against it (they stay on the party's account). Refused in signed-off books.",
    )
    note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500,
        help_text="Why it is being removed. Kept in the change log.",
    )
