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
from ledger.tally_plan import STANDARD_TYPES

ROW_ACTIONS = ["create", "match", "conflict", "needs_group", "skipped"]
CONFLICT_KINDS = ["group_differs", "name_variant", "duplicate_in_file", "needs_group"]


class TallyImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="The ledger masters exported from Tally: .xml (preferred), .xlsx, .csv or .json."
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
            raise serializers.ValidationError("Upload an .xml, .xlsx, .csv or .json file exported from Tally.")
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
    voucher_types = serializers.JSONField(
        required=False,
        help_text=(
            "What the firm's own voucher types count as: {Tally's name: a standard type}, for example "
            '{"GST SALE": "sales"}. The standard types are sales, purchase, credit note, debit note, journal, payment, receipt and contra.'
        ),
    )

    def validate_voucher_types(self, value):
        if not isinstance(value, dict) or len(value) > 50:
            raise serializers.ValidationError("Send an object of voucher type names, at most 50.")
        for name, standard in value.items():
            if not isinstance(name, str) or not isinstance(standard, str) or standard not in STANDARD_TYPES:
                raise serializers.ValidationError(f"{name!r} must count as one of: {', '.join(STANDARD_TYPES)}.")
        return value

    def validate_file(self, upload):
        if upload.size == 0:
            raise serializers.ValidationError("The file is empty.")
        if upload.size > settings.MAX_TALLY_IMPORT_BYTES * 2:
            raise serializers.ValidationError("The file is far too large to be a vouchers export.")
        if not upload.name.lower().endswith((".xml", ".json")):
            raise serializers.ValidationError("Upload the .xml or .json file exported from Tally.")
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
    unknown_types = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        help_text="The firm's own voucher types the importer does not know, with how many vouchers each has: the person says what each counts as.",
    )
    type_map = serializers.DictField(
        child=serializers.CharField(), required=False, help_text="What the person said the firm's own voucher types count as."
    )
    existing_entries = serializers.IntegerField(
        required=False, help_text="Entries the client already has in the dates this import covers; posting on top needs the person's say-so."
    )
    existing_statement_rows = serializers.IntegerField(
        required=False, help_text="Bank statement rows already in those dates for the accounts this import writes to."
    )
    date_from = serializers.CharField()
    date_to = serializers.CharField()


class TallyPostSerializer(serializers.Serializer):
    allow_overlap = serializers.BooleanField(
        required=False, default=False, help_text="The person has seen that entries or bank rows already stand in these dates and wants the import posted anyway."
    )


class TallyRefreshSerializer(serializers.Serializer):
    voucher_types = serializers.JSONField(
        required=False,
        help_text="What the firm's own voucher types count as; left out, the choice made earlier stands.",
    )

    def validate_voucher_types(self, value):
        return TallyVouchersUploadSerializer().validate_voucher_types(value)


class TallyProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()


class TallyVoucherRunSerializer(serializers.ModelSerializer):
    counts = TallyVoucherCountsSerializer()
    result = serializers.SerializerMethodField()
    rows = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField(help_text="The file as it was uploaded; it stays with the client's documents.")
    document = serializers.UUIDField(source="document_id", allow_null=True, read_only=True, help_text="The stored file, downloadable from the documents.")
    uploaded_by_name = serializers.SerializerMethodField()
    posting = serializers.SerializerMethodField(help_text="A worker is writing this import's vouchers now.")
    progress = serializers.SerializerMethodField(help_text="How far posting has got, while it is being posted.")
    error = serializers.SerializerMethodField(help_text="Why the last attempt to post stopped, in words for the person.")

    class Meta:
        model = LedgerImportRun
        fields = [
            "id", "kind", "status", "financial_year", "counts", "rows", "result", "created_at", "expires_at", "confirmed_at",
            "file_name", "document", "uploaded_by_name", "posting", "progress", "error",
        ]

    @extend_schema_field(TallyVoucherResultSerializer(allow_null=True))
    def get_result(self, run):
        if run.status == ImportStatus.PREVIEW:  # while it waits or is being posted, ``result`` holds only the progress notes
            return None
        return run.result or None

    def get_file_name(self, run) -> str:
        return run.document.original_filename if run.document_id else ""

    def get_uploaded_by_name(self, run) -> str:
        user = run.uploaded_by
        return (getattr(user, "get_full_name", lambda: "")() or getattr(user, "email", "")) if user else ""

    def get_posting(self, run) -> bool:
        return bool(run.status == ImportStatus.PREVIEW and (run.result or {}).get("posting"))

    @extend_schema_field(TallyProgressSerializer(allow_null=True))
    def get_progress(self, run):
        progress = (run.result or {}).get("progress") if run.status == ImportStatus.PREVIEW else None
        return progress or None

    def get_error(self, run) -> str:
        return str((run.result or {}).get("error", "")) if run.status == ImportStatus.PREVIEW else ""

    @extend_schema_field(TallyVoucherRowSerializer(many=True))
    def get_rows(self, run):
        # Only what the screen shows: never the voucher's lines, figures or the party's GSTIN.
        keys = ("ordinal", "type", "number", "date", "party", "total_paise", "action", "bill", "reason", "note")
        return TallyVoucherRowSerializer([{k: row.get(k) for k in keys} for row in run.rows], many=True).data


class TallyVoucherRunSummarySerializer(TallyVoucherRunSerializer):
    """One line of the queue: the same, without the voucher rows (a year's import has thousands)."""

    rows = None  # a declared field of the parent, dropped here

    class Meta(TallyVoucherRunSerializer.Meta):
        fields = [f for f in TallyVoucherRunSerializer.Meta.fields if f != "rows"]


class TallyDiscoverSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        max_length=12,
        help_text="Tally XML files: voucher exports and bank ledger reports, any mix, up to 12.",
    )
    bank_ledgers = serializers.JSONField(
        required=False,
        help_text="For a bank report whose bank ledger could not be told from the file name: {file name: the bank ledger's name in Tally}.",
    )

    def validate_files(self, files):
        for upload in files:
            if upload.size == 0:
                raise serializers.ValidationError(f"{upload.name} is empty.")
            if upload.size > settings.MAX_TALLY_IMPORT_BYTES * 2:
                raise serializers.ValidationError(f"{upload.name} is far too large to be a Tally export.")
            if not upload.name.lower().endswith((".xml", ".json")):
                raise serializers.ValidationError(f"{upload.name} is not an .xml or .json file exported from Tally.")
        return files


class TallyLedgerProposalSerializer(serializers.Serializer):
    name = serializers.CharField()
    group = serializers.ChoiceField(choices=LedgerGroup.choices, help_text="The group the files suggest; the person may change it.")
    reason = serializers.CharField(help_text="Why that group, in a few words.")
    uses = serializers.IntegerField(help_text="How many times the files use the ledger.")
    unsure = serializers.BooleanField(help_text="The evidence was thin or mixed; look at this one.")


class TallyAccountProposalSerializer(serializers.Serializer):
    ledger = serializers.CharField()
    kind = serializers.ChoiceField(choices=["BANK", "LOAN", "CARD"])
    bank_code = serializers.CharField()
    account_number = serializers.CharField(allow_blank=True, help_text="Read from the ledger's name; blank when the person must type it.")


class TallyReportFileSerializer(serializers.Serializer):
    file = serializers.CharField()
    ledger = serializers.CharField(allow_blank=True, help_text="The bank ledger the report is for; blank when it could not be told.")
    rows = serializers.IntegerField()
    left_out = serializers.IntegerField(help_text="Rows a bank report cannot rebuild (several ledgers on the voucher).")


class TallyIgnoredFileSerializer(serializers.Serializer):
    file = serializers.CharField()
    reason = serializers.CharField()


class TallyDiscoveryResponseSerializer(serializers.Serializer):
    vouchers = serializers.IntegerField()
    voucher_files = serializers.IntegerField()
    master_files = serializers.IntegerField(help_text="Ledger-list files whose groups were read from Tally itself.")
    ignored = TallyIgnoredFileSerializer(many=True, help_text="Files that could not be used, each with why; the rest were read.")
    reports = TallyReportFileSerializer(many=True)
    ledgers = TallyLedgerProposalSerializer(many=True)
    accounts = TallyAccountProposalSerializer(many=True)


class TallyLedgerChoiceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    group = serializers.ChoiceField(choices=LedgerGroup.choices)


class TallyAccountChoiceSerializer(serializers.Serializer):
    ledger = serializers.CharField(max_length=255)
    kind = serializers.ChoiceField(choices=["BANK", "LOAN", "CARD"])
    bank_code = serializers.CharField(max_length=16, required=False, default="BANK")
    account_number = serializers.CharField(max_length=40, allow_blank=True, required=False, default="")


class TallySetupSerializer(serializers.Serializer):
    ledgers = TallyLedgerChoiceSerializer(many=True, max_length=20_000)
    accounts = TallyAccountChoiceSerializer(many=True, required=False, default=list, max_length=200)


class TallySetupResultSerializer(serializers.Serializer):
    ledgers = serializers.IntegerField(help_text="Ledgers created.")
    accounts = serializers.IntegerField(help_text="Bank accounts opened.")
    waiting_for_a_number = serializers.ListField(
        child=serializers.CharField(), help_text="Accounts not opened because no account number was given."
    )


class TallyBankReportUploadSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(), max_length=12, help_text="Tally bank ledger reports, exported as XML; the same period for every report."
    )
    accounts = serializers.ListField(
        child=serializers.UUIDField(), max_length=12, help_text="The client's bank account each report is for, in the same order as `files`."
    )
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        if len(attrs["files"]) != len(attrs["accounts"]):
            raise serializers.ValidationError("Give one bank account for each report.")
        for upload in attrs["files"]:
            if upload.size == 0:
                raise serializers.ValidationError(f"{upload.name} is empty.")
            if upload.size > settings.MAX_TALLY_IMPORT_BYTES * 2:
                raise serializers.ValidationError(f"{upload.name} is far too large to be a bank report.")
            if not upload.name.lower().endswith(".xml"):
                raise serializers.ValidationError(f"{upload.name} is not an .xml file exported from Tally.")
        return attrs
