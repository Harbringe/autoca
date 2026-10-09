"""Uploaded invoices and what was read from them: drafts for a person to confirm."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from core.money import format_inr
from integrations import files
from integrations.pdf.base import PdfExtractionError
from integrations.registry import get_pdf
from ledger.invoice_intake import MAX_INVOICE_BYTES, MAX_INVOICE_PAGES
from ledger.models import BillKind, InvoiceReading


class InvoiceUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="The invoice: a PDF, an Excel sheet (.xlsx), a CSV, a Word file (.docx) or a photo or scan (JPG, PNG, WEBP, TIFF).")
    kind = serializers.ChoiceField(
        choices=[BillKind.PURCHASE, BillKind.SALES],
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Leave blank to have it told from the client's own GSTIN. `PURCHASE`: a supplier's invoice to the client. "
            "`SALES`: the client's invoice to a customer."
        ),
    )

    book = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Leave true to have a certain invoice booked at once. False reads it into a draft for a person to complete and book.",
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
        kind = files.sniff(upload.read(), upload.name)
        upload.seek(0)
        if kind is None:
            raise serializers.ValidationError(files.describe_refusal(upload.read(16), upload.name))
        if kind != files.PDF:
            return upload
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


class SayKindSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[BillKind.PURCHASE, BillKind.SALES])


class CheckSerializer(serializers.Serializer):
    name = serializers.CharField()
    ok = serializers.BooleanField()
    detail = serializers.CharField(allow_blank=True)


class ReadItemSerializer(serializers.Serializer):
    description = serializers.CharField()
    hsn_sac = serializers.CharField(allow_blank=True)
    quantity = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    rate_paise = PaiseField(allow_null=True)
    amount_paise = PaiseField(allow_null=True, help_text="The line's taxable amount.")
    gst_rate = serializers.FloatField(allow_null=True, help_text="Percent.")
    discount_paise = PaiseField(allow_null=True)
    cgst_paise = PaiseField(allow_null=True)
    sgst_paise = PaiseField(allow_null=True)
    igst_paise = PaiseField(allow_null=True)
    total_paise = PaiseField(allow_null=True, help_text="The line total, when printed.")


class RejectedValueSerializer(serializers.Serializer):
    field = serializers.CharField(help_text="Which field the model gave a value for.")
    value = serializers.CharField(help_text="What the model said.")
    why = serializers.CharField(help_text="Why it was not used.")


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
    due_date = serializers.DateField(allow_null=True)
    supplier_address = serializers.CharField(allow_blank=True)
    supplier_pan = serializers.CharField(allow_blank=True)
    buyer_name = serializers.CharField(allow_blank=True)
    buyer_address = serializers.CharField(allow_blank=True)
    place_of_supply = serializers.CharField(allow_blank=True)
    payment_mode = serializers.CharField(allow_blank=True, help_text="cash, card, upi, bank_transfer, cheque or credit; blank when the page does not say.")
    payment_terms = serializers.CharField(allow_blank=True)
    currency = serializers.CharField(allow_blank=True)
    expense_hint = serializers.CharField(allow_blank=True, help_text="A few words for what it was for, to suggest a ledger.")
    items = ReadItemSerializer(many=True, help_text="The invoice's lines, when the model read them.")
    tcs_paise = PaiseField(help_text="Tax collected at source, when printed.")
    other_charges_paise = PaiseField(help_text="Freight and other charges outside the taxable value.")
    discount_paise = PaiseField(allow_null=True, help_text="The invoice's total discount, when printed.")
    details = serializers.DictField(
        child=serializers.CharField(),
        help_text="Other facts printed on the document: document_type, irn, ack_no, ack_date, eway_bill_no, vehicle_no, po_number, "
        "po_date, ship_to_name, ship_to_address, supplier_email, supplier_phone, buyer_pan, bank_name, bank_account_no, bank_ifsc, "
        "amount_in_words, notes, reverse_charge. Only those that were found.",
    )
    rejected = RejectedValueSerializer(
        many=True, help_text="Values the model gave that failed their check and so were left out of the fields, with why."
    )
    as_read = serializers.JSONField(help_text="The model's reply as it came (bounded), to trace a wrong field.")
    unsure = serializers.ListField(
        child=serializers.CharField(), help_text="Fields the reader said it could not read clearly (a scan), to check against the page."
    )


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
    auto_booked = serializers.BooleanField(
        help_text="The system booked the bill from this file. A person can change it like any other bill."
    )
    attention = serializers.CharField(
        allow_blank=True, help_text="Why the system did not book this file itself, in words. Blank when it did or nothing is wrong."
    )
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
                "due_date": fields.get("due_date"),
                "supplier_address": fields.get("supplier_address", ""),
                "supplier_pan": fields.get("supplier_pan", ""),
                "buyer_name": fields.get("buyer_name", ""),
                "buyer_address": fields.get("buyer_address", ""),
                "place_of_supply": fields.get("place_of_supply", ""),
                "payment_mode": fields.get("payment_mode", ""),
                "payment_terms": fields.get("payment_terms", ""),
                "currency": fields.get("currency", ""),
                "expense_hint": fields.get("expense_hint", ""),
                "items": fields.get("items", []),
                "tcs_paise": fields.get("tcs_paise", 0),
                "other_charges_paise": fields.get("other_charges_paise", 0),
                "discount_paise": fields.get("discount_paise"),
                "details": fields.get("details", {}),
                "rejected": fields.get("rejected", []),
                "as_read": fields.get("as_read", {}),
                "unsure": fields.get("unsure", []),
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
        "auto_booked": reading.auto_booked,
        "attention": reading.attention,
        "payments": list(payments),
    }
