"""An invoice file in, a draft reading out, and what a person can do with it.

Upload turns a PDF into a ``Document`` (the evidence, registered with every other file) and an ``InvoiceReading`` (what it
appears to say, with the arithmetic that proves or faults it). Nothing is booked from here. A person books it, which is the
ordinary purchase or sales voucher with the file attached (``note_booked`` then closes the reading), or attaches the file to
a bill that was booked by hand first, or sets it aside. Until then the reading is an open item, so a file cannot sit unseen.

A scan or photo has no text layer and is refused for now rather than read badly; the reading carries the reason.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from django.db import IntegrityError, transaction
from django.utils import timezone

from classify.models import CRYPTO_PURPOSE, Party
from core.crypto import blind_index, decrypt_text_for_firm, encrypt_for_firm
from core.identity import invoice_key, normalise_gstin
from core.rbac import require_permission
from documents.models import Document, DocumentKind, DocumentStatus, PipelineTier
from integrations.pdf.base import PdfExtractionError
from integrations.registry import get_pdf, get_storage
from ledger.invoice_reader import read_invoice
from ledger.models import Bill, BillKind, InvoiceReading, ReadingStatus

PAYLOAD_PURPOSE = "ledger.invoice_reading"
MAX_INVOICE_BYTES = 15 * 1024 * 1024
MAX_INVOICE_PAGES = 30


class IntakeError(ValueError):
    """The file or the request cannot be taken as an invoice. The message says what to do."""


def _document_kind(kind: str) -> str:
    return DocumentKind.PURCHASE_INVOICE if kind == BillKind.PURCHASE else DocumentKind.SALES_INVOICE


def _counterparty_gstin(kind: str, gstins: list[str]) -> str:
    """The other party's GSTIN: the supplier's on a purchase, the buyer's on a sale.

    Suppliers print their own GSTIN first, so on a purchase it is the first one found and on a sale (where the first is the
    client's own) the next. It is only a suggestion; the person confirms it.
    """
    if kind == BillKind.PURCHASE:
        return gstins[0] if gstins else ""
    return gstins[1] if len(gstins) > 1 else ""


def _key_for(client, kind: str, gstins: list[str], invoice_no: str) -> str:
    if not invoice_no:
        return ""
    # The books key a purchase on the supplier's GSTIN and a sale on the client's own, which is the first one printed.
    identity = gstins[0] if gstins else ""
    return invoice_key(client.firm_id, identity, invoice_no) if identity else ""


def read_upload(*, client, data: bytes, filename: str, kind: str, uploaded_by) -> tuple[InvoiceReading, bool]:
    """Register the file and read it. Returns the reading and whether this file is new."""
    if kind not in (BillKind.PURCHASE, BillKind.SALES):
        raise IntakeError("Say whether this is a purchase invoice or a sales invoice.")
    if len(data) > MAX_INVOICE_BYTES:
        raise IntakeError("This file is larger than 15 MB. An invoice is a few hundred kilobytes; check it is the right file.")
    if not data.startswith(b"%PDF"):
        raise IntakeError(
            "Only PDF invoices can be read for now. For a photo or a scan, key the invoice in Purchases & Sales and attach the file there."
        )

    digest = Document.digest(data)
    existing = Document.objects.filter(firm_id=client.firm_id, sha256=digest).first()
    if existing is not None:
        reading = InvoiceReading.objects.filter(firm_id=client.firm_id, document=existing).first()
        if reading is None:
            raise IntakeError("This exact file is already on file as something other than an invoice.")
        if reading.client_id != client.pk:
            raise IntakeError(
                "This exact file is already on file for another client of the firm. Check you have the right client open."
            )
        return reading, False

    try:
        pdf = get_pdf().extract(data)
    except PdfExtractionError as exc:
        raise IntakeError(f"This PDF could not be opened: {exc}") from exc
    if pdf.page_count > MAX_INVOICE_PAGES:
        raise IntakeError(f"This PDF has {pdf.page_count} pages; an invoice has a few. Check it is the right file.")

    storage = get_storage()
    key = storage.tenant_key(client.firm_id, "clients", str(client.id), "invoices", f"{digest}.pdf")
    storage.put(key, data, content_type="application/pdf")

    has_text = pdf.has_text_layer
    with transaction.atomic():
        document = Document.objects.create(
            firm_id=client.firm_id,
            client=client,
            kind=_document_kind(kind),
            original_filename=filename[:255],
            sha256=digest,
            storage_key=key,
            byte_size=len(data),
            page_count=pdf.page_count,
            pipeline_tier=PipelineTier.TEXT_LAYER if has_text else PipelineTier.UNKNOWN,
            status=DocumentStatus.PARSED if has_text else DocumentStatus.FAILED,
            failure_reason="" if has_text else "No text layer: a scan or photo.",
            uploaded_by=uploaded_by,
        )
        if not has_text:
            reading = InvoiceReading.objects.create(
                firm_id=client.firm_id,
                client=client,
                document=document,
                kind=kind,
                unreadable_reason="This looks like a scan or a photo, which cannot be read yet. Key the invoice in by hand; the file stays attached.",
            )
            return reading, True

        parsed = read_invoice(pdf.text)
        payload = {
            "supplier_name": parsed.supplier_name,
            "gstins": parsed.gstins,
            "counterparty_gstin": _counterparty_gstin(kind, parsed.gstins),
            "invoice_no": parsed.invoice_no,
            "invoice_date": parsed.invoice_date.isoformat() if parsed.invoice_date else None,
            "taxable_paise": parsed.taxable_paise,
            "cgst_paise": parsed.cgst_paise,
            "sgst_paise": parsed.sgst_paise,
            "igst_paise": parsed.igst_paise,
            "cess_paise": parsed.cess_paise,
            "round_off_paise": parsed.round_off_paise,
            "total_paise": parsed.total_paise,
        }
        try:
            reading = InvoiceReading.objects.create(
                firm_id=client.firm_id,
                client=client,
                document=document,
                kind=kind,
                proved=parsed.proved,
                checks=[asdict(c) for c in parsed.checks],
                payload_enc=encrypt_for_firm(json.dumps(payload), client.firm_id, PAYLOAD_PURPOSE),
                invoice_key=_key_for(client, kind, parsed.gstins, parsed.invoice_no),
            )
        except IntegrityError as exc:  # the same file arriving twice at once
            raise IntakeError("This file was uploaded a moment ago by someone else.") from exc
    return reading, True


def fields_of(reading: InvoiceReading) -> dict:
    """What was read, decrypted. Empty for a reading that found nothing."""
    if not reading.payload_enc:
        return {}
    return json.loads(decrypt_text_for_firm(bytes(reading.payload_enc), reading.firm_id, PAYLOAD_PURPOSE))


def suggested_party(reading: InvoiceReading) -> Party | None:
    """The client's party whose GSTIN is the one read, if there is one."""
    gstin = normalise_gstin(fields_of(reading).get("counterparty_gstin", ""))
    if not gstin:
        return None
    return Party.objects.filter(
        firm_id=reading.firm_id, client=reading.client, gstin_hash=blind_index(gstin, reading.firm_id, CRYPTO_PURPOSE)
    ).first()


def matching_bill(reading: InvoiceReading) -> Bill | None:
    """A bill already booked from this very invoice (same supplier GSTIN and number), if it has no file yet."""
    if not reading.invoice_key or reading.status != ReadingStatus.OPEN:
        return None
    return (
        Bill.objects.filter(
            firm_id=reading.firm_id, client=reading.client, kind=reading.kind, invoice_key=reading.invoice_key,
            document__isnull=True, reading__isnull=True,
        )
        .select_related("party")
        .first()
    )


def _open_reading(reading: InvoiceReading) -> None:
    if reading.status != ReadingStatus.OPEN:
        raise IntakeError("This invoice has already been dealt with.")


def attach_to_bill(reading: InvoiceReading, bill: Bill, *, membership) -> InvoiceReading:
    """Say that this file is the invoice behind a bill booked by hand. The bill is not touched; the link is the reading's."""
    require_permission(membership, "journal.approve")
    _open_reading(reading)
    if bill.client_id != reading.client_id or bill.firm_id != reading.firm_id:
        raise IntakeError("That bill belongs to a different client.")
    if bill.kind != reading.kind:
        raise IntakeError("That bill is not the same kind of invoice (purchase or sales).")
    if bill.document_id is not None or InvoiceReading.objects.filter(bill=bill).exists():
        raise IntakeError("That bill already has an invoice file.")
    reading.bill = bill
    reading.status = ReadingStatus.ATTACHED
    reading.decided_by = membership.user
    reading.decided_at = timezone.now()
    reading.save(update_fields=["bill", "status", "decided_by", "decided_at"])
    return reading


def discard(reading: InvoiceReading, *, membership) -> InvoiceReading:
    """Set a reading aside: the file stays on record, and it leaves the open items."""
    require_permission(membership, "journal.approve")
    _open_reading(reading)
    reading.status = ReadingStatus.DISCARDED
    reading.decided_by = membership.user
    reading.decided_at = timezone.now()
    reading.save(update_fields=["status", "decided_by", "decided_at"])
    return reading


def note_booked(document: Document, bill: Bill, *, user) -> None:
    """A bill was booked with this document: close its reading, if it has one and it was still open."""
    reading = InvoiceReading.objects.filter(firm_id=document.firm_id, document=document).first()
    if reading is None or reading.status != ReadingStatus.OPEN:
        return
    reading.bill = bill
    reading.status = ReadingStatus.BOOKED
    reading.decided_by = user
    reading.decided_at = timezone.now()
    reading.save(update_fields=["bill", "status", "decided_by", "decided_at"])

