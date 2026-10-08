"""An invoice file in, a reading out, and what happens to it.

Upload turns a PDF into a ``Document`` (the evidence, registered with every other file) and an ``InvoiceReading`` (what it
appears to say, with the arithmetic that proves or faults it). Nothing is booked from here. A person books it, which is the
ordinary purchase or sales voucher with the file attached (``note_booked`` then closes the reading), or attaches the file to
a bill that was booked by hand first, or sets it aside. Until then the reading is an open item, so a file cannot sit unseen.

When the file is certain (``try_auto_book``) the system books it itself as an ordinary bill that a person can change, and
settles it against its bank payment if exactly one matches. When anything is not certain it books nothing and says why.

A scan or photo has no text layer: it is read by the vision model when that is switched on, and proved by the same
arithmetic; otherwise the reading carries the reason.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from classify.models import CRYPTO_PURPOSE, Party
from core.access import require_posting_rights
from core.crypto import blind_index, decrypt_text_for_firm, encrypt_for_firm
from core.identity import invoice_key, normalise_gstin
from core.rbac import require_permission
from documents.models import Document, DocumentKind, DocumentStatus, PipelineTier
from integrations import files
from integrations.pdf.base import PdfExtractionError
from integrations.registry import get_llm, get_storage
from ledger import invoice_vision
from ledger.invoice_reader import read_invoice
from ledger.models import Bill, BillKind, InvoiceReading, ReadingStatus

PAYLOAD_PURPOSE = "ledger.invoice_reading"
MAX_INVOICE_BYTES = 15 * 1024 * 1024
MAX_INVOICE_PAGES = 30


class IntakeError(ValueError):
    """The file or the request cannot be taken as an invoice. The message says what to do."""


def _document_kind(kind: str) -> str:
    if not kind:
        return DocumentKind.OTHER
    return DocumentKind.PURCHASE_INVOICE if kind == BillKind.PURCHASE else DocumentKind.SALES_INVOICE


def own_gstins(client) -> set[str]:
    """The GSTINs the client is registered under, which is how a file is told to be its purchase or its sale."""
    from gst.models import GstRegistration

    return {
        r.gstin for r in GstRegistration.objects.filter(firm_id=client.firm_id, client=client, is_active=True) if r.gstin
    }


def detect_kind(client, parsed) -> tuple[str, str]:
    """Whether the file is the client's purchase or sale, and if not known, why not (in words for the alert).

    The client is the buyer on a purchase and the issuer on a sale, so it is decided by which printed GSTIN is the client's
    own. Never guessed: with no registration on record, or no GSTIN of the client's on the file, or the page not saying who
    is who, the kind is left blank for a person to say.
    """
    own = own_gstins(client)
    if not own:
        return "", (
            "This client's own GSTIN is not on record, so the file could not be told as a purchase or a sale. "
            "Add it under GST, or say which this is."
        )
    supplier, buyer = parsed.supplier_gstin, parsed.buyer_gstin
    if supplier in own and buyer in own:
        return "", "Both GSTINs on this invoice are the client's own. Say whether it is a purchase or a sale."
    if supplier in own:
        return BillKind.SALES, ""
    if buyer in own:
        return BillKind.PURCHASE, ""
    if any(g in own for g in parsed.gstins):
        return "", "The client's GSTIN is on this file but it is not clear who issued it. Say whether it is a purchase or a sale."
    return "", (
        "None of the GSTINs on this invoice is the client's own. Check it is the right client, "
        "then say whether it is a purchase or a sale."
    )


def _counterparty_gstin(kind: str, supplier: str, buyer: str) -> str:
    """The other party's GSTIN: the supplier's on a purchase, the buyer's on a sale."""
    return supplier if kind == BillKind.PURCHASE else buyer if kind == BillKind.SALES else ""


def _roles(client, gstins: list[str], supplier: str, buyer: str, kind: str) -> tuple[str, str]:
    """Who issued it and who is billed, once the kind is known, when the page did not say which GSTIN is which.

    The client's own GSTIN is the buyer's on a purchase and the issuer's on a sale; the other one is the counterparty.
    """
    own = own_gstins(client)
    others = [g for g in gstins if g not in own]
    ours = [g for g in gstins if g in own]
    if kind == BillKind.PURCHASE:
        supplier = supplier if supplier and supplier not in own else (others[0] if others else "")
        buyer = buyer if buyer in own else (ours[0] if ours else buyer)
    elif kind == BillKind.SALES:
        supplier = supplier if supplier in own else (ours[0] if ours else supplier)
        buyer = buyer if buyer and buyer not in own else (others[0] if others else "")
    return supplier, buyer


def _key_for(client, supplier: str, invoice_no: str) -> str:
    # The books key a purchase on the supplier's GSTIN, and a sale on the client's own, who is the supplier there too.
    return invoice_key(client.firm_id, supplier, invoice_no) if supplier and invoice_no else ""


def _payload_of(parsed, kind: str) -> dict:
    return {
        "supplier_name": parsed.supplier_name,
        "buyer_name": parsed.buyer_name,
        "unsure": parsed.unsure,
        "gstins": parsed.gstins,
        "supplier_gstin": parsed.supplier_gstin,
        "buyer_gstin": parsed.buyer_gstin,
        "counterparty_gstin": _counterparty_gstin(kind, parsed.supplier_gstin, parsed.buyer_gstin),
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


def read_upload(*, client, data: bytes, filename: str, kind: str = "", uploaded_by) -> tuple[InvoiceReading, bool]:
    """Register the file and read it. Returns the reading and whether this file is new.

    ``kind`` is optional: when it is not given the file is told apart by the client's own GSTIN (``detect_kind``).
    """
    if kind and kind not in (BillKind.PURCHASE, BillKind.SALES):
        raise IntakeError("Say whether this is a purchase invoice or a sales invoice, or leave it for the system to tell.")
    if len(data) > MAX_INVOICE_BYTES:
        raise IntakeError("This file is larger than 15 MB. An invoice is a few hundred kilobytes; check it is the right file.")
    digest = Document.digest(data)
    existing = Document.objects.filter(firm_id=client.firm_id, client=client, sha256=digest).first()
    if existing is not None:
        reading = InvoiceReading.objects.filter(firm_id=client.firm_id, document=existing).first()
        if reading is None:
            raise IntakeError("This exact file is already on file as something other than an invoice.")
        return reading, False

    try:
        loaded = files.load(data, filename)
    except PdfExtractionError as exc:
        raise IntakeError(str(exc) if isinstance(exc, files.UnsupportedFileError) else f"This file could not be opened: {exc}") from exc
    pdf = loaded.document
    if pdf.page_count > MAX_INVOICE_PAGES:
        raise IntakeError(f"This file has {pdf.page_count} pages; an invoice has a few. Check it is the right file.")

    parsed = None
    unreadable = ""
    tier = PipelineTier.TEXT_LAYER
    if pdf.has_text_layer:
        parsed = read_invoice(pdf.text)
    elif invoice_vision.enabled():
        try:
            parsed = invoice_vision.read_scanned_invoice(
                data, pdf.page_count, get_llm(), client=client, page_images=loaded.images
            )
            tier = PipelineTier.VISION
        except invoice_vision.InvoiceVisionError as exc:
            unreadable = str(exc)
    else:
        unreadable = (
            "This looks like a scan or a photo, and reading scans is not switched on. "
            "Key the invoice in by hand; the file stays attached."
        )

    attention = ""
    chosen = kind
    if parsed is not None and not kind:
        chosen, attention = detect_kind(client, parsed)
    if parsed is not None and chosen:
        parsed.supplier_gstin, parsed.buyer_gstin = _roles(client, parsed.gstins, parsed.supplier_gstin, parsed.buyer_gstin, chosen)

    storage = get_storage()
    key = storage.tenant_key(client.firm_id, "clients", str(client.id), "invoices", f"{digest}.{loaded.extension}")
    storage.put(key, data, content_type=loaded.content_type)

    with transaction.atomic():
        document = Document.objects.create(
            firm_id=client.firm_id,
            client=client,
            kind=_document_kind(chosen),
            original_filename=filename[:255],
            sha256=digest,
            storage_key=key,
            byte_size=len(data),
            page_count=pdf.page_count,
            pipeline_tier=tier if parsed is not None else PipelineTier.UNKNOWN,
            status=DocumentStatus.PARSED if parsed is not None else DocumentStatus.FAILED,
            failure_reason=unreadable[:255],
            uploaded_by=uploaded_by,
        )
        if parsed is None:
            reading = InvoiceReading.objects.create(
                firm_id=client.firm_id, client=client, document=document, kind=chosen,
                unreadable_reason=unreadable, attention=unreadable[:255],
            )
            return reading, True

        issuer = parsed.supplier_gstin or (parsed.gstins[0] if parsed.gstins else "")
        try:
            reading = InvoiceReading.objects.create(
                firm_id=client.firm_id,
                client=client,
                document=document,
                kind=chosen,
                proved=parsed.proved,
                checks=[asdict(c) for c in parsed.checks],
                payload_enc=encrypt_for_firm(json.dumps(_payload_of(parsed, chosen)), client.firm_id, PAYLOAD_PURPOSE),
                invoice_key=_key_for(client, issuer, parsed.invoice_no),
                attention=attention[:255],
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


def payment_candidates(reading: InvoiceReading, limit: int = 5) -> list[dict]:
    """Bank rows that look like the payment for this invoice: the suggested party, the invoice's total, the right direction.

    So the invoice is not an island: when a payment of exactly that amount to (or from) that party is already in the books,
    it is shown beside the invoice. If it was posted to a head such as Sales or an expense, booking the invoice would count
    the same cost or revenue twice, and the payment can then be moved onto the party's account (see the To fix list).
    Only a suggestion: it is never linked on its own.
    """
    from banking.models import StatementTransaction
    from ledger.models import JournalEntry

    party = suggested_party(reading)
    total = fields_of(reading).get("total_paise")
    if party is None or not total or not reading.kind:
        return []
    rows = StatementTransaction.objects.filter(
        firm_id=reading.firm_id, bank_account__client=reading.client, classification__party=party
    ).filter(debit_paise=total) if reading.kind == BillKind.PURCHASE else StatementTransaction.objects.filter(
        firm_id=reading.firm_id, bank_account__client=reading.client, classification__party=party, credit_paise=total
    )
    found = []
    for txn in rows.select_related("classification__ledger").order_by("value_date")[:limit]:
        ledger = txn.classification.ledger
        entry = JournalEntry.objects.filter(firm_id=reading.firm_id, source_transaction=txn).first()
        found.append(
            {
                "date": txn.value_date,
                "narration": " ".join((txn.narration or "").split())[:80],
                "posted_to": ledger.name if (ledger and entry) else None,
                "on_party_account": bool(ledger and ledger.is_party_account),
                "entry": entry.pk if entry else None,
            }
        )
    return found


def _open_reading(reading: InvoiceReading) -> None:
    if reading.status != ReadingStatus.OPEN:
        raise IntakeError("This invoice has already been dealt with.")


def attach_to_bill(reading: InvoiceReading, bill: Bill, *, membership) -> InvoiceReading:
    """Say that this file is the invoice behind a bill booked by hand. The bill is not touched; the link is the reading's."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, reading.client)
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
    require_posting_rights(membership, reading.client)
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
    reading.auto_booked = False
    reading.attention = ""
    reading.decided_by = user
    reading.decided_at = timezone.now()
    reading.save(update_fields=["bill", "status", "auto_booked", "attention", "decided_by", "decided_at"])



# ---------------------------------------------------------------------------
# Booking by the system, and the person's way to say what it could not tell
# ---------------------------------------------------------------------------


def _find_or_make_party(client, kind: str, gstin: str, name: str) -> Party:
    """The client's party for this GSTIN, or a new one when there is no party of that name at all.

    What a file says is not trusted to change what the books already know: a party of the same name that has a different
    GSTIN, or none, is never taken over or duplicated here (a person decides which party it is). A party is never invented
    without a name.
    """
    from classify.models import PartyRole

    digest = blind_index(gstin, client.firm_id, CRYPTO_PURPOSE)
    party = Party.objects.filter(firm_id=client.firm_id, client=client, gstin_hash=digest).first()
    if party is not None:
        return party
    if kind == BillKind.SALES:
        raise IntakeError(
            "This customer is not on record yet. A new customer is added by a person, so choose or add the customer and book it."
        )
    name = " ".join((name or "").split())[:255]
    if len(name) < 3:
        raise IntakeError("The party's name could not be read. Choose the party and book it.")
    if Party.objects.filter(firm_id=client.firm_id, client=client, canonical_name__iexact=name).exists():
        raise IntakeError(
            f"{name} is already a party here with a different (or no) GSTIN than the one on this invoice. "
            "Choose which party it is and book it."
        )
    role = PartyRole.VENDOR if kind == BillKind.PURCHASE else PartyRole.CUSTOMER
    party = Party(firm_id=client.firm_id, client=client, canonical_name=name, role=role)
    party.set_gstin(gstin)
    party.save()
    return party


def _why_not(reading: InvoiceReading, membership) -> str:
    """Why this reading is not booked by the system, or blank when it is safe to. Plain words for the alert."""
    if not reading.kind:
        return reading.attention or "Say whether this is a purchase or a sale."
    if not reading.proved:
        return "The figures on this invoice do not add up, so it was not booked. Check them and book it."
    try:
        require_permission(membership, "journal.approve")
        require_posting_rights(membership, reading.client)
    except PermissionDenied:
        return "Waiting for someone who may approve entries to book this."
    return ""


def try_auto_book(reading: InvoiceReading, *, membership) -> InvoiceReading:
    """Book the invoice if everything is certain: the kind, the proof, the party, the books open for its date.

    The result is an ordinary bill, with the file attached, that a person can change (``billing.revise``) like any other.
    When anything is not certain nothing is booked and the reading says why in ``attention``, which is also what the alert
    shows, so staff deal with exactly that and nothing else.
    """
    if reading.status != ReadingStatus.OPEN or reading.unreadable_reason:
        return reading
    reason = _why_not(reading, membership)
    if not reason:
        reason = _book(reading, membership)
    if reason != reading.attention:
        reading.attention = reason[:255]
        reading.save(update_fields=["attention"])
    return reading


def _book(reading: InvoiceReading, membership) -> str:
    from ledger import billing

    client = reading.client
    fields = fields_of(reading)
    purchase = reading.kind == BillKind.PURCHASE
    gstin = normalise_gstin(fields.get("counterparty_gstin", ""))
    if not gstin:
        return f"No GSTIN was found for the {'supplier' if purchase else 'customer'}. Choose the party and book it."
    name = fields.get("supplier_name") if purchase else fields.get("buyer_name")
    own = (fields.get("buyer_gstin") if purchase else fields.get("supplier_gstin")) or ""
    document = reading.document
    try:
        with transaction.atomic():
            party = _find_or_make_party(client, reading.kind, gstin, name)
            if purchase and party.tds_section:
                raise IntakeError(
                    f"TDS (section {party.tds_section}) normally applies to {party.canonical_name}. "
                    "Enter the amount deducted and book it."
                )
            if purchase and party.rcm_default:
                raise IntakeError(
                    f"Reverse charge applies to {party.canonical_name}. Confirm the tax treatment and book it."
                )
            head = billing.standard_ledger(client, "Purchases" if purchase else "Sales")
            data = billing.BillInput(
                reference=fields["invoice_no"],
                bill_date=datetime.date.fromisoformat(fields["invoice_date"]),
                narration=f"Booked automatically from {document.original_filename or 'the uploaded invoice'}. Check it; change it if it is wrong.",
                document=document,
                own_gstin=own,
                cgst=fields.get("cgst_paise", 0),
                sgst=fields.get("sgst_paise", 0),
                igst=fields.get("igst_paise", 0),
                cess=fields.get("cess_paise", 0),
                round_off=fields.get("round_off_paise", 0),
            )
            post = billing.post_purchase if purchase else billing.post_sales
            bill = post(client, party, [(head, fields["taxable_paise"])], data, membership=membership)
            note_booked(document, bill, user=membership.user)
            InvoiceReading.objects.filter(pk=reading.pk).update(auto_booked=True, attention="")
    except (billing.BillingError, IntakeError, PermissionDenied) as exc:
        return str(exc)
    reading.refresh_from_db()
    settle_payment(bill)
    return ""


def settle_payment(bill: Bill) -> bool:
    """Match the bill to its payment when exactly one bank payment on the party's account is for exactly its total.

    Two cases, both only when unambiguous: a payment on the party's account with nothing allocated yet, and money a person
    held on account or as an advance because the invoice had not arrived (it is applied now that it has). Two payments of
    the same amount, a payment posted to some other head, or one inside signed-off books are left for a person; the screen
    shows the payment beside the invoice. A payment that comes *after* the invoice is settled by the person who approves
    it, with this bill proposed (``ledger.settlement``): that decision is deliberately never automatic.
    """
    from ledger import billing, editing
    from ledger.models import AllocationKind, BillAllocation, JournalLine

    lines = (
        JournalLine.objects.filter(
            firm_id=bill.firm_id, entry__client_id=bill.client_id, party_id=bill.party_id,
            entry__source_transaction__isnull=False,
        )
        .exclude(direction=bill.direction)
        .select_related("entry")
    )
    free = [line for line in lines if billing.line_unallocated(line) == bill.total_paise]
    held = list(
        BillAllocation.objects.filter(
            firm_id=bill.firm_id, client_id=bill.client_id, bill__isnull=True,
            kind__in=(AllocationKind.ON_ACCOUNT, AllocationKind.ADVANCE),
            line__party_id=bill.party_id, line__entry__source_transaction__isnull=False,
            amount_paise=bill.total_paise,
        )
        .exclude(line__direction=bill.direction)
        .select_related("line__entry")
    )
    if len(free) + len(held) == 0:
        # Nothing on the party's account yet: look for a bank row not placed or posted that is plainly this payment.
        from ledger import matching

        return matching.match_bill(bill)
    if len(free) + len(held) != 1:
        return False
    try:
        with transaction.atomic():
            if free:
                editing.require_editable(free[0].entry)
                billing.allocate(free[0], amount_paise=bill.total_paise, bill=bill)
            else:
                editing.require_editable(held[0].line.entry)
                billing.apply_unapplied(held[0], bill, amount_paise=bill.total_paise)
    except (billing.BillingError, editing.EntryLockedError, ValueError):
        return False
    return True


def say_kind(reading: InvoiceReading, kind: str, *, membership) -> InvoiceReading:
    """A person says whether this file is a purchase or a sale. The system then tries to book it as usual."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, reading.client)
    _open_reading(reading)
    if kind not in (BillKind.PURCHASE, BillKind.SALES):
        raise IntakeError("Say whether this is a purchase invoice or a sales invoice.")
    client = reading.client
    fields = fields_of(reading)
    if not fields:
        raise IntakeError("Nothing could be read from this file, so there is nothing to book from it. Key the invoice in by hand.")
    supplier, buyer = _roles(client, fields.get("gstins", []), fields.get("supplier_gstin", ""), fields.get("buyer_gstin", ""), kind)
    fields.update(supplier_gstin=supplier, buyer_gstin=buyer, counterparty_gstin=_counterparty_gstin(kind, supplier, buyer))
    reading.kind = kind
    reading.attention = ""
    reading.payload_enc = encrypt_for_firm(json.dumps(fields), reading.firm_id, PAYLOAD_PURPOSE)
    reading.invoice_key = _key_for(client, supplier, fields.get("invoice_no", ""))
    reading.save(update_fields=["kind", "attention", "payload_enc", "invoice_key"])
    Document.objects.filter(pk=reading.document_id).update(kind=_document_kind(kind))
    return try_auto_book(reading, membership=membership)
