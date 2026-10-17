"""Importing a client's chart of accounts and opening balances from a Tally export.

The preview is the response to the upload, and the same shape is read back later:
every row says what would happen to it (``action``), why, and, where a person
must decide, which choices exist (``conflict.choices``). Nothing is applied by
the upload; ``confirm`` applies exactly the choices sent with it.
"""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.fields import MoneySerializerMixin, PaiseField
from classify.models import LedgerGroup
from ledger.models import ImportKind, ImportStatus, LedgerImportRun
from ledger.tally_import import ALL_CHOICES, BANK_CHOICES
from ledger.tally_parse import ALLOWED_EXTENSIONS

ROW_ACTIONS = ["create", "match", "conflict", "needs_group", "skipped"]
CONFLICT_KINDS = ["group_differs", "name_variant", "duplicate_in_file", "needs_group"]


class TallyImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="The ledger masters exported from Tally: .xml (preferred), .xlsx or .csv."
    )
    financial_year = serializers.IntegerField(
        min_value=2000,
        max_value=2100,
        help_text="The year the opening balances are as at the start of: 2025 means 1 April 2025.",
    )
    include_openings = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "False imports the chart of accounts only. Use it when the file's balances are not those "
            "at the start of the year (`tally_year_mismatch`)."
        ),
    )

    def validate_file(self, upload):
        if upload.size == 0:
            raise serializers.ValidationError("The file is empty.")
        # Size is checked again by the parser, which answers 413; this stops a huge body being read at all.
        if upload.size > settings.MAX_TALLY_IMPORT_BYTES * 2:
            raise serializers.ValidationError("The file is far too large to be a list of ledgers.")
        if not upload.name.lower().endswith(ALLOWED_EXTENSIONS):
            raise serializers.ValidationError("Upload an .xml, .xlsx or .csv file exported from Tally.")
        return upload


class TallyResolutionSerializer(serializers.Serializer):
    row = serializers.IntegerField(min_value=0, help_text="The preview row's `row` number.")
    choice = serializers.ChoiceField(
        choices=list(ALL_CHOICES),
        required=False,
        help_text="One of that row's `conflict.choices`.",
    )
    group = serializers.ChoiceField(
        choices=LedgerGroup.choices,
        required=False,
        help_text="With `choice: group`: which of our groups a group of the firm's own belongs to.",
    )
    bank = serializers.ChoiceField(
        choices=list(BANK_CHOICES),
        required=False,
        help_text="For a row whose `bank` panel needs a decision: one of `bank.choices`.",
    )

    def validate(self, attrs):
        if "choice" not in attrs and "bank" not in attrs:
            raise serializers.ValidationError("Give a choice, a bank choice, or both.")
        return attrs


class TallyConfirmSerializer(serializers.Serializer):
    resolutions = TallyResolutionSerializer(many=True, required=False, default=list, max_length=20_000)


# ---------------------------------------------------------------------------
# Response shapes. Documentation only, for the generated types: the views return
# what ``ledger.tally_import`` staged.
# ---------------------------------------------------------------------------


class TallyConflictSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CONFLICT_KINDS)
    choices = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "What the person may choose. `keep_ours`, `take_tally` (take Tally's group), "
            "`use_tally_name` (rename ours to Tally's spelling, entries move with it), "
            "`use_this_spelling` (this duplicate replaces the first one), `group` (name one of "
            "our groups in `group`), `skip` (leave this line out)."
        ),
    )
    default = serializers.CharField(
        allow_null=True,
        help_text="What a screen may pre-select. Null means the person must choose; nothing is assumed.",
    )
    pair_row = serializers.IntegerField(
        required=False, allow_null=True, help_text="For `duplicate_in_file`: the first row it duplicates."
    )


class TallyBankPanelSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("ours_paise", "tally_paise")

    account_id = serializers.UUIDField()
    label = serializers.CharField()
    ours_paise = PaiseField(allow_null=True, help_text="The opening already confirmed on the bank account, or null.")
    tally_paise = PaiseField(help_text="Tally's opening for this ledger. Debits positive.")
    status = serializers.ChoiceField(
        choices=["propose", "agree", "conflict", "nothing"],
        help_text=(
            "`propose`: no opening is confirmed yet, so Tally's will be written to the bank account. "
            "`agree`: the same figure, nothing to do. `conflict`: two different figures; choose one in `bank`. "
            "`nothing`: no opening confirmed and none in the file. "
            "The ledger never gets a second copy of the number."
        ),
    )
    choices = serializers.ListField(child=serializers.CharField())
    default = serializers.CharField(allow_null=True)


class TallyRowSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("opening_paise",)

    row = serializers.IntegerField(help_text="The number to quote in a resolution. Zero-based.")
    ordinal = serializers.IntegerField(help_text="The line's position in the file (the sheet row, in a spreadsheet).")
    name = serializers.CharField(help_text="As Tally spells it, whitespace tidied.")
    alias = serializers.CharField(allow_null=True)
    tally_group = serializers.CharField(help_text="The group the file puts it under, as written.")
    tally_group_path = serializers.CharField(allow_null=True)
    our_group = serializers.ChoiceField(
        choices=LedgerGroup.choices, allow_null=True, help_text="Null when the group is one of the firm's own and needs `choice: group`."
    )
    opening_paise = PaiseField(help_text="Debits positive, credits negative. Zero when the file gives none.")
    action = serializers.ChoiceField(
        choices=ROW_ACTIONS,
        help_text=(
            "`create` a new ledger; `match` an existing one (same name, same group); `conflict` the person must "
            "choose (see `conflict`); `needs_group` a group of the firm's own, choose one of ours; `skipped` "
            "not imported, with the reason."
        ),
    )
    reason = serializers.CharField(allow_blank=True)
    ledger_id = serializers.UUIDField(allow_null=True, help_text="Our ledger this line matches or collides with.")
    ledger_name = serializers.CharField(allow_null=True)
    ledger_group = serializers.ChoiceField(choices=LedgerGroup.choices, allow_null=True)
    posted_lines = serializers.IntegerField(help_text="Journal lines already posted to our ledger.")
    conflict = TallyConflictSerializer(allow_null=True)
    bank = TallyBankPanelSerializer(allow_null=True)


class TallyCountsSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("debit_paise", "credit_paise", "difference_paise")

    create = serializers.IntegerField()
    match = serializers.IntegerField()
    conflict = serializers.IntegerField()
    needs_group = serializers.IntegerField()
    skipped = serializers.IntegerField()
    with_opening = serializers.IntegerField()
    bank_conflicts = serializers.IntegerField()
    debit_paise = PaiseField(help_text="Total of the debit openings in the file, if every default is taken.")
    credit_paise = PaiseField()
    difference_paise = PaiseField(
        help_text=(
            "Debits less credits. Zero when the file's openings balance; otherwise exactly what the "
            "reports show as Difference in opening balances."
        )
    )
    entries_in_year = serializers.IntegerField(
        help_text="Entries already posted in that year. The Trial Balance changes by the openings."
    )


class TallyResultSerializer(MoneySerializerMixin, serializers.Serializer):
    money = ("debit_paise", "credit_paise", "difference_paise")

    created = serializers.IntegerField(help_text="Ledgers created.")
    matched = serializers.IntegerField(help_text="Existing ledgers the file matched.")
    renamed = serializers.IntegerField()
    regrouped = serializers.IntegerField()
    openings = serializers.IntegerField(help_text="Ledger openings stored.")
    bank_openings = serializers.IntegerField(help_text="Openings written to a bank account instead.")
    skipped = serializers.IntegerField()
    debit_paise = PaiseField()
    credit_paise = PaiseField()
    difference_paise = PaiseField()


class TallyImportSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=ImportKind.choices)
    status = serializers.ChoiceField(choices=ImportStatus.choices)
    financial_year = serializers.IntegerField()
    source_format = serializers.CharField()
    include_openings = serializers.BooleanField()
    books_from = serializers.DateField(allow_null=True, help_text="The date the file says the company's books begin, if it does.")
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(help_text="A preview that is not confirmed by then cannot be.")
    confirmed_at = serializers.DateTimeField(allow_null=True)
    counts = TallyCountsSerializer()
    result = serializers.SerializerMethodField(help_text="Present once confirmed.")

    @extend_schema_field(TallyResultSerializer(allow_null=True))
    def get_result(self, run):
        # An unconfirmed run stores an empty dict, which is "no result yet", not a result of zeros.
        return TallyResultSerializer(run.result).data if run.result else None


class TallyImportDetailSerializer(TallyImportSummarySerializer):
    rows = TallyRowSerializer(many=True)


class TallyErrorSerializer(serializers.Serializer):
    code = serializers.CharField(
        help_text=(
            "Stable code: tally_file_unreadable (422), tally_file_too_large (413), tally_year_mismatch (422), "
            "tally_run_stale (409), tally_conflicts_unresolved (409), tally_rule (409), entry_locked (409), "
            "ledger_name_taken (409), invalid (400), forbidden (403), not_found (404)."
        )
    )
    detail = serializers.CharField(help_text="A sentence for a person; show it as it is.")


class TallyVouchersUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="The vouchers exported from Tally in XML.")
    date_from = serializers.DateField(required=False, help_text="Import vouchers dated on or after this day.")
    date_to = serializers.DateField(required=False, help_text="Import vouchers dated on or before this day.")

    def validate_file(self, upload):
        if upload.size == 0:
            raise serializers.ValidationError("The file is empty.")
        if upload.size > settings.MAX_TALLY_IMPORT_BYTES * 2:
            raise serializers.ValidationError("The file is far too large to be a vouchers export.")
        if not upload.name.lower().endswith(".xml"):
            raise serializers.ValidationError("Upload the .xml file exported from Tally.")
        return upload


class TallyVoucherRowSerializer(serializers.Serializer):
    ordinal = serializers.IntegerField(help_text="The voucher's position in the file.")
    type = serializers.CharField(help_text="Tally's voucher type, as written.")
    number = serializers.CharField(allow_blank=True)
    date = serializers.CharField(allow_blank=True, help_text="ISO date; empty when the voucher's date could not be read.")
    party = serializers.CharField(allow_blank=True)
    total_paise = PaiseField(help_text="The voucher's value: the debit side.")
    action = serializers.ChoiceField(choices=["post", "skip"])
    bill = serializers.BooleanField(help_text="A bill is made from it (an invoice or a note with a party and a number).")
    reason = serializers.CharField(allow_blank=True, help_text="Why it is skipped.")
    note = serializers.CharField(allow_blank=True, help_text="Posted, but something a person should know (for example, no bill).")


class TallyVoucherFailureSerializer(serializers.Serializer):
    guid = serializers.CharField()
    reason = serializers.CharField()


class TallyVoucherResultSerializer(serializers.Serializer):
    posted = serializers.IntegerField(required=False)
    bills = serializers.IntegerField(required=False)
    skipped = serializers.IntegerField(required=False, help_text="Already imported earlier, so not written again.")
    failed = TallyVoucherFailureSerializer(many=True, required=False)
    bank_rows = serializers.IntegerField(required=False, help_text="Statement rows written for bank vouchers.")
    unmatched_bills = serializers.IntegerField(
        required=False, help_text="Bill references on payments that could not be applied; left on account for a person to apply."
    )
    stock_entries = serializers.IntegerField(required=False, help_text="Stock movements written for item invoices.")
    rules_learned = serializers.IntegerField(required=False, help_text="Rules learned from the bank history; they place rows but never post on their own.")
    undone = serializers.IntegerField(required=False)


class TallyVoucherCountsSerializer(serializers.Serializer):
    vouchers = serializers.IntegerField()
    will_post = serializers.IntegerField()
    will_make_bill = serializers.IntegerField()
    skipped = serializers.IntegerField()
    bank_waiting = serializers.IntegerField(
        help_text="Bank vouchers left out (no bank account in AutoCA, a loan or card account, or more than two lines); the bank ledger is incomplete."
    )
    bank_rows = serializers.IntegerField(help_text="Statement rows the bank vouchers will write.")
    stock_lines = serializers.IntegerField(help_text="Stock item lines that will go into the stock register.")
    by_type = serializers.DictField(child=serializers.IntegerField())
    date_from = serializers.CharField()
    date_to = serializers.CharField()


class TallyVoucherRunSerializer(serializers.ModelSerializer):
    counts = TallyVoucherCountsSerializer()
    result = serializers.SerializerMethodField()
    rows = serializers.SerializerMethodField()

    class Meta:
        model = LedgerImportRun
        fields = ["id", "kind", "status", "financial_year", "counts", "rows", "result", "created_at", "expires_at", "confirmed_at"]

    @extend_schema_field(TallyVoucherResultSerializer(allow_null=True))
    def get_result(self, run):
        return run.result or None

    @extend_schema_field(TallyVoucherRowSerializer(many=True))
    def get_rows(self, run):
        # Only what the screen shows: never the voucher's lines, figures or the party's GSTIN.
        keys = ("ordinal", "type", "number", "date", "party", "total_paise", "action", "bill", "reason", "note")
        return TallyVoucherRowSerializer([{k: row.get(k) for k in keys} for row in run.rows], many=True).data
