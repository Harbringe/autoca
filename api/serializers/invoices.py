"""Uploaded invoices and what was read from them: drafts for a person to confirm."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr
from integrations.pdf.base import PdfExtractionError
from integrations.registry import get_pdf
from ledger.invoice_intake import MAX_INVOICE_BYTES, MAX_INVOICE_PAGES
from ledger.models import BillKind, InvoiceReading


class InvoiceUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="The invoice as a PDF with a text layer.")
    kind = serializers.ChoiceField(
        choices=[BillKind.PURCHASE, BillKind.SALES],
        help_text="`PURCHASE`: a supplier's invoice to the client. `SALES`: the client's invoice to a customer.",
    )

    def validate_file(self, upload):
        """Size, signature and page count are checked before a byte is read into memory or extracted.

        The page count is read first, cheaply, because extraction cost grows with it; the same reasoning as a statement.
        An unreadable file is left for the intake to report in its own words.
        """
        if upload.size == 0:
            raise serializers.ValidationError("The file is empty.")
        if upload.size > MAX_INVOICE_BYTES:
            raise serializers.ValidationError(
                f"This file is {upload.size / (1024 * 1024):.1f} MB; the limit is {MAX_INVOICE_BYTES // (1024 * 1024)} MB."
            )
        head = upload.read(5)
        upload.seek(0)
        if head != b"%PDF-":
            raise serializers.ValidationError(
                "Only PDF invoices can be read for now. For a photo or a scan, key the invoice in Purchases & Sales."
            )
        try:
            pages = get_pdf().page_count(upload.read())
        except PdfExtractionError:
            pages = 0
        finally:
            upload.seek(0)
        if pages > MAX_INVOICE_PAGES:
            raise serializers.ValidationError(
                f"This PDF has {pages} pages; an invoice has a few. Check it is the right file."
            )
        return upload


class AttachSerializer(serializers.Serializer):
    bill = serializers.UUIDField(help_text="The bill, booked by hand earlier, that this file is the invoice for.")


class CheckSerializer(serializers.Serializer):
    name = serializers.CharField()
    ok = serializers.BooleanField()
    detail = serializers.CharField(allow_blank=True)


class ReadFieldsSerializer(serializers.Serializer):
    supplier_name = serializers.CharField(allow_blank=True)
    gstins = serializers.ListField(child=serializers.CharField(), help_text="Every valid GSTIN printed on the invoice, in order.")
    counterparty_gstin = serializers.CharField(
        allow_blank=True, help_text="The other party's: the supplier on a purchase, the buyer on a sale."
    )
    invoice_no = serializers.CharField(allow_blank=True)
    invoice_date = serializers.DateField(allow_null=True)
    taxable_paise = PaiseField(allow_null=True)
    cgst_paise = PaiseField()
    sgst_paise = PaiseField()
    igst_paise = PaiseField()
    cess_paise = PaiseField()
    round_off_paise = PaiseField()
    total_paise = PaiseField(allow_null=True)
    total_display = serializers.CharField(allow_null=True)


class PartyHintSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class BillHintSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    reference = serializers.CharField()
    party_name = serializers.CharField()


class PaymentHintSerializer(serializers.Serializer):
    date = serializers.DateField()
    narration = serializers.CharField(allow_blank=True)
    posted_to = serializers.CharField(allow_null=True, help_text="The head it was posted to, or null while it waits in Review.")
    on_party_account = serializers.BooleanField()
    entry = serializers.UUIDField(allow_null=True)


class InvoiceReadingSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    document = serializers.UUIDField(help_text="The stored file; download it from the documents route.")
    filename = serializers.CharField(allow_blank=True)
    proved = serializers.BooleanField(help_text="Every arithmetic and format check passed.")
    unreadable_reason = serializers.CharField(allow_blank=True)
    checks = CheckSerializer(many=True)
    created_at = serializers.DateTimeField()
    read = ReadFieldsSerializer(allow_null=True, help_text="What was read; null when nothing could be.")
    suggested_party = PartyHintSerializer(allow_null=True, help_text="The client's party with the GSTIN that was read, if any.")
    matching_bill = BillHintSerializer(
        allow_null=True, help_text="A bill already booked from this very invoice that has no file yet."
    )
    bill = serializers.UUIDField(allow_null=True)
    payments = PaymentHintSerializer(
        many=True, help_text="Bank rows that look like the payment for this invoice: same party, same total. A suggestion only."
    )


def reading_payload(reading: InvoiceReading, fields: dict, party, matching, payments=()) -> dict:
    total = fields.get("total_paise")
    return {
        "id": reading.pk,
        "kind": reading.kind,
        "status": reading.status,
        "status_display": reading.get_status_display(),
        "document": reading.document_id,
        "filename": reading.document.original_filename,
        "proved": reading.proved,
        "unreadable_reason": reading.unreadable_reason,
        "checks": reading.checks,
        "created_at": reading.created_at,
        "read": (
            {
                "supplier_name": fields.get("supplier_name", ""),
                "gstins": fields.get("gstins", []),
                "counterparty_gstin": fields.get("counterparty_gstin", ""),
                "invoice_no": fields.get("invoice_no", ""),
                "invoice_date": fields.get("invoice_date"),
                "taxable_paise": fields.get("taxable_paise"),
                "cgst_paise": fields.get("cgst_paise", 0),
                "sgst_paise": fields.get("sgst_paise", 0),
                "igst_paise": fields.get("igst_paise", 0),
                "cess_paise": fields.get("cess_paise", 0),
                "round_off_paise": fields.get("round_off_paise", 0),
                "total_paise": total,
                "total_display": format_inr(total) if total is not None else None,
            }
            if fields
            else None
        ),
        "suggested_party": {"id": party.pk, "name": party.canonical_name} if party else None,
        "matching_bill": (
            {"id": matching.pk, "reference": matching.reference, "party_name": matching.party.canonical_name}
            if matching
            else None
        ),
        "bill": reading.bill_id,
        "payments": list(payments),
    }
