"""Reading an invoice from its page images, for a PDF with no text layer (a scan or a photo saved as PDF).

The same rule as a scanned statement (``banking.scan``): the model only copies what is printed; nothing it says is trusted.
Every figure goes through the same proof as a text read (``invoice_reader.reading_from_fields``): the arithmetic must tie,
the GSTINs must pass their check character, the number and date must be there. A reading that does not prove is still
shown, with what failed, and is never booked by the system on its own.

Used only when the firm has switched ``VISION_READING`` on, because page images cannot be masked. Nothing is stored: the
images exist in memory for the length of the call.
"""

from __future__ import annotations

import json
import time

from django.conf import settings

from banking.scan import render_pages
from integrations.llm.base import LLMError, LLMRateLimited, LLMUnavailable
from ledger.invoice_reader import Reading, reading_from_fields
from usage.recorder import record

SYSTEM = (
    "You copy the contents of a scanned GST tax invoice into JSON. You do not calculate, correct, round or infer "
    "anything: copy each figure exactly as printed, digit for digit. If something is not on the pages, use an empty "
    "string. Reply with one JSON object and nothing else."
)

INSTRUCTION = (
    "These are the pages of one invoice. Return JSON with exactly these keys: "
    '"supplier_name" (who issued the invoice), "supplier_gstin" (the issuer\'s GSTIN), "buyer_name" and "buyer_gstin" '
    '(the party billed, "bill to"), "invoice_no", "invoice_date" (DD-MM-YYYY), "taxable" (total taxable value before '
    'tax), "cgst", "sgst", "igst", "cess" (the total tax amounts, not the rates), "round_off" (with its sign) and '
    '"total" (the invoice total). Amounts as printed, without the currency symbol.'
)


class InvoiceVisionError(ValueError):
    """The scan could not be read; the message says what to do."""


def enabled() -> bool:
    return bool(getattr(settings, "VISION_READING", False))


def read_scanned_invoice(data: bytes, page_count: int, llm, *, client=None) -> Reading:
    limit = int(settings.VISION_MAX_PAGES)
    if page_count > limit:
        raise InvoiceVisionError(f"This scan has {page_count} pages; scans are read up to {limit} pages at a time.")
    pages = render_pages(data)
    started = time.monotonic()
    try:
        reply = llm.complete_json_with_images(SYSTEM, INSTRUCTION, pages, max_tokens=2048)
    except LLMUnavailable as exc:
        raise InvoiceVisionError("The model that reads scans is not set up. Set the model in the server settings.") from exc
    except LLMRateLimited as exc:
        _record(client, "RATE_LIMITED", None, started, len(pages))
        raise InvoiceVisionError("The reading service is busy or its allowance is used up. Try this scan again in a few minutes.") from exc
    except LLMError as exc:
        _record(client, "ERROR", None, started, len(pages))
        raise InvoiceVisionError(f"The scan could not be read: {exc}") from exc
    _record(client, "OK", reply, started, len(pages))
    try:
        fields = json.loads(reply.text)
    except ValueError as exc:
        raise InvoiceVisionError("The scan was read, but the reply was not understandable.") from exc
    if not isinstance(fields, dict):
        raise InvoiceVisionError("The scan was read, but the reply was not understandable.")
    return reading_from_fields(fields)


def _record(client, outcome, response, started, pages) -> None:
    """Counts and tokens only, for the platform owner's usage page; never the images or what was read."""
    record(
        purpose="SCAN",
        outcome=outcome,
        response=response,
        firm_id=getattr(client, "firm_id", None),
        client_id=getattr(client, "pk", None),
        latency_ms=int((time.monotonic() - started) * 1000),
        pages=pages,
    )
