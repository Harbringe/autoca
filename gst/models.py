"""GST reconciliation: registrations, the two datasets, and what was decided.

A self-contained add-on. Nothing outside ``gst/`` imports it except the API
layer and the isolation factories, and it reads the books only through
``classify.Party`` (for a supplier's reverse-charge default). Removing it means
deleting this app, its routes and its tab.

Three groups of tables, differing in how mutable they are:

* ``GstRegistration`` -- one row per GSTIN a client holds. A client with
  registrations in three states has three, and every run is against exactly one:
  the returns are filed per GSTIN, so the reconciliation is too.
* ``ReconRun`` and its rows -- staging. Rebuilt freely until a CA signs it off,
  which is the same rule the books follow.
* ``ReconDecision`` -- append-only. What a person decided about a row, and who
  signed the run off. Corrections are new decisions, never edits.

Suppliers' GSTINs are stored the way ``classify.Party`` stores them -- encrypted,
with a blind index under the same purpose -- so the two join on the hash.
"""

from __future__ import annotations

from django.db import models

from classify.models import CRYPTO_PURPOSE
from core.crypto import blind_index, decrypt_text_for_firm, encrypt_for_firm
from core.models import Client, FirmScopedModel, User, UUIDModel
from documents.models import Document


class GstinMixin(models.Model):
    """An encrypted GSTIN with a blind index, as ``Party`` keeps one."""

    gstin_enc = models.BinaryField(blank=True, null=True)
    gstin_hash = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        abstract = True

    @property
    def gstin(self) -> str:
        if not self.gstin_enc:
            return ""
        return decrypt_text_for_firm(bytes(self.gstin_enc), self.firm_id, CRYPTO_PURPOSE)

    def set_gstin(self, gstin: str) -> None:
        gstin = (gstin or "").strip().upper()
        if not gstin:
            self.gstin_enc, self.gstin_hash = None, ""
            return
        self.gstin_enc = encrypt_for_firm(gstin, self.firm_id, CRYPTO_PURPOSE)
        self.gstin_hash = blind_index(gstin, self.firm_id, CRYPTO_PURPOSE)


class RegistrationType(models.TextChoices):
    REGULAR = "regular", "Regular"
    COMPOSITION = "composition", "Composition"
    OTHER = "other", "Other"


class GstRegistration(UUIDModel, FirmScopedModel, GstinMixin):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="gst_registrations")
    #: The two-digit state code, kept separately so a state-wise view needs no decryption.
    state_code = models.CharField(max_length=2)
    registration_type = models.CharField(
        max_length=16, choices=RegistrationType.choices, default=RegistrationType.REGULAR
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "gst_registration"
        ordering = ["state_code", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "gstin_hash"], name="uniq_gst_registration_per_client"
            ),
        ]

    def __str__(self) -> str:
        return f"GSTIN registration, state {self.state_code}"


class RunStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SIGNED_OFF = "signed_off", "Signed off"


class ReconRun(UUIDModel, FirmScopedModel):
    """One GSTIN, one return period."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="gst_runs")
    registration = models.ForeignKey(GstRegistration, on_delete=models.CASCADE, related_name="runs")
    #: First day of the return month.
    period_start = models.DateField()
    register_document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    portal_document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The register was built from the books' own bills (``gst.books``) rather than uploaded as a file.
    register_from_books = models.BooleanField(default=False, db_default=False)
    status = models.CharField(max_length=16, choices=RunStatus.choices, default=RunStatus.DRAFT)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    signed_off_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    signed_off_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "gst_recon_run"
        ordering = ["-period_start", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "registration", "period_start"], name="uniq_gst_run_per_period"
            ),
        ]


class InvoiceRow(GstinMixin):
    """The shared shape of a register row and a portal row."""

    invoice_no = models.CharField(max_length=64)
    invoice_date = models.DateField(null=True, blank=True)
    supplier_name = models.CharField(max_length=255, blank=True, default="")
    hsn = models.CharField(max_length=16, blank=True, default="")
    section = models.CharField(max_length=4, default="B2B")  # B2B CDN DN IMPG ISD
    taxable_paise = models.BigIntegerField(default=0)
    igst_paise = models.BigIntegerField(default=0)
    cgst_paise = models.BigIntegerField(default=0)
    sgst_paise = models.BigIntegerField(default=0)
    cess_paise = models.BigIntegerField(default=0)
    #: From GSTR-2B: whether the portal says the credit can be taken, and why not.
    itc_available = models.BooleanField(default=True)
    itc_reason = models.CharField(max_length=16, blank=True, default="")
    #: For an amended invoice, the number it replaces.
    original_no = models.CharField(max_length=64, blank=True, default="")
    #: Position in the source file, so a message can say "row 14".
    source_row = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True


class RegisterInvoice(UUIDModel, FirmScopedModel, InvoiceRow):
    run = models.ForeignKey(ReconRun, on_delete=models.CASCADE, related_name="register_rows")
    category = models.CharField(max_length=128, blank=True, default="")
    rcm = models.BooleanField(default=False)
    blocked = models.BooleanField(default=False)

    class Meta:
        db_table = "gst_register_invoice"
        ordering = ["source_row"]

    def __str__(self) -> str:
        return f"Register invoice {self.invoice_no}"


class Gstr2bInvoice(UUIDModel, FirmScopedModel, InvoiceRow):
    run = models.ForeignKey(ReconRun, on_delete=models.CASCADE, related_name="portal_rows")

    class Meta:
        db_table = "gst_gstr2b_invoice"
        ordering = ["source_row"]

    def __str__(self) -> str:
        return f"GSTR-2B invoice {self.invoice_no}"


class ReconMatch(UUIDModel, FirmScopedModel):
    """The engine's verdict on one row. Rebuilt on every run until sign-off."""

    run = models.ForeignKey(ReconRun, on_delete=models.CASCADE, related_name="matches")
    kind = models.CharField(max_length=24)
    itc_status = models.CharField(max_length=24)
    register_invoice = models.ForeignKey(
        RegisterInvoice, null=True, on_delete=models.CASCADE, related_name="+"
    )
    portal_invoice = models.ForeignKey(
        Gstr2bInvoice, null=True, on_delete=models.CASCADE, related_name="+"
    )
    eligible_paise = models.BigIntegerField(default=0)
    ineligible_paise = models.BigIntegerField(default=0)
    cause = models.TextField(blank=True, default="")
    action = models.TextField(blank=True, default="")
    differences = models.JSONField(default=dict, blank=True)
    timing = models.BooleanField(default=False)

    class Meta:
        db_table = "gst_recon_match"
        ordering = ["kind", "created_at"]


class DecisionKind(models.TextChoices):
    ACCEPT_MATCH = "accept_match", "Accept as a match"
    CLAIM_ITC = "claim_itc", "Claim the credit"
    DISALLOW_ITC = "disallow_itc", "Disallow the credit"
    DEFER = "defer", "Defer to a later month"
    NOTE = "note", "Note"
    SIGN_OFF = "sign_off", "Signed off the run"


class ReconDecision(UUIDModel, FirmScopedModel):
    """What a person decided. Append-only; the latest for an invoice wins.

    Keyed by ``match_key`` -- a blind index of supplier GSTIN and normalised
    invoice number -- rather than by a ``ReconMatch`` row, because matches are
    rebuilt on every run and an append-only table cannot have its foreign keys
    nulled when they are. The key is the invoice's identity, and it survives.
    A run that has decisions cannot be deleted: the delete is refused by the
    same trigger that refuses the edit.
    """

    run = models.ForeignKey(ReconRun, on_delete=models.CASCADE, related_name="decisions")
    match_key = models.CharField(max_length=64, blank=True, default="", db_index=True)
    kind = models.CharField(max_length=16, choices=DecisionKind.choices)
    note = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name="+")

    class Meta:
        db_table = "gst_recon_decision"
        ordering = ["created_at"]
