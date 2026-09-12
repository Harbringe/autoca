"""The registry of every file a firm uploads, whatever kind it is.

One table for bank statements, purchase invoices, GSTR-2B extracts and
registers, rather than one per feature. That is not tidiness -- three things
only work if there is a single registry:

* **Duplicate detection is free and global.** ``UNIQUE(firm, sha256)`` catches
  the same file re-uploaded, regardless of who uploaded it, under which client,
  or as which kind. A per-feature table would catch it only within that feature.
* **Provenance is uniform.** Every derived row -- a statement transaction now, a
  GSTR-2B line later -- points back to a document and a line number within it.
  "Where did this entry come from?" is then one join, not a different join per
  document type.
* **Retention is one policy.** Indian law requires financial records to be kept
  for years, and the object-storage lifecycle rules that implement that are
  written against object keys. One key scheme, one rule set.

A document records the *file*. What was read out of it lives in the app that
knows how to read it: ``banking.Statement`` for the parsed period and balances
of a bank statement, and the GST app's rows later. The split matters when a
parser is fixed and re-run -- the file is unchanged and keeps its identity,
while everything derived from it is replaceable.
"""

from __future__ import annotations

import hashlib

from django.db import models

from core.models import Client, FirmScopedModel, User, UUIDModel


class DocumentKind(models.TextChoices):
    BANK_STATEMENT = "BANK_STATEMENT", "Bank statement"
    PURCHASE_INVOICE = "PURCHASE_INVOICE", "Purchase invoice"
    SALES_INVOICE = "SALES_INVOICE", "Sales invoice"
    GSTR2B = "GSTR2B", "GSTR-2B extract"
    REGISTER = "REGISTER", "Purchase or sales register"
    TALLY_EXPORT = "TALLY_EXPORT", "Tally export"
    OTHER = "OTHER", "Other"


class PipelineTier(models.TextChoices):
    """How the text was got out of the file.

    Recorded because it changes how much the result should be trusted. A
    born-digital extraction is the exact bytes the bank's own renderer emitted;
    an OCR read is a guess with a confidence score. A reviewer looking at an
    odd-looking row deserves to know which of those they are reading.
    """

    UNKNOWN = "UNKNOWN", "Not yet routed"
    TEXT_LAYER = "TEXT_LAYER", "Born-digital text layer"
    OCR = "OCR", "Optical character recognition"
    MANUAL = "MANUAL", "Keyed in by hand"


class DocumentStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    PARSED = "PARSED", "Parsed"
    FAILED = "FAILED", "Could not be read"


class Document(UUIDModel, FirmScopedModel):
    """One uploaded file, kept as the evidence behind everything derived from it."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=24, choices=DocumentKind.choices)

    original_filename = models.CharField(max_length=255, blank=True)
    #: SHA-256 of the bytes as uploaded. The identity of the file.
    sha256 = models.CharField(max_length=64, db_index=True)
    storage_key = models.CharField(max_length=512, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    page_count = models.PositiveSmallIntegerField(default=0)

    pipeline_tier = models.CharField(
        max_length=16, choices=PipelineTier.choices, default=PipelineTier.UNKNOWN
    )
    status = models.CharField(
        max_length=16, choices=DocumentStatus.choices, default=DocumentStatus.RECEIVED
    )
    #: Why a FAILED document failed, in the words the parser used.
    failure_reason = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_documents"
    )

    class Meta:
        db_table = "documents_document"
        ordering = ["-created_at"]
        constraints = [
            # The same file, uploaded twice, is one document. Scoped to the firm
            # rather than globally: two firms holding the same file is a
            # coincidence, and a shared row would be a cross-tenant link.
            models.UniqueConstraint(fields=["firm", "sha256"], name="uniq_document_per_firm_sha256"),
        ]
        indexes = [
            models.Index(fields=["firm", "client", "kind"], name="idx_document_client_kind"),
        ]

    def __str__(self) -> str:
        return self.original_filename or f"{self.get_kind_display()} {self.sha256[:12]}"

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
