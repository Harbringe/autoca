"""Reading an invoice from its page images, for a PDF with no text layer (a scan or a photo saved as PDF).

The same rule as a scanned statement (``banking.scan``): the model only copies what is printed; nothing it says is trusted.
Every figure goes through the same proof as a text read (``invoice_reader.reading_from_fields``): the arithmetic must tie,
the GSTINs must pass their check character, the number and date must be there. A reading that does not prove is still
shown, with what failed, and is never booked by the system on its own.

Used only when the firm has switched ``VISION_READING`` on, because page images cannot be masked. The images are never stored: they
exist in memory for the length of the call. (The reply and the extracted text are filed only when the developer's debug archive is
on: integrations/debug_archive.py.)
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
    "You copy the contents of an invoice or receipt (a scan, a photo or a page) into JSON. You do not calculate, correct, round or infer "
    "anything: every value is what the page prints, digit for digit. Reply with one JSON object and nothing else, in "
    "exactly the shape you are given. Use null for anything that is not on the pages or that you cannot read."
)

INSTRUCTION = (
    "These are the pages of one invoice or receipt. Return one JSON object with exactly these keys.\n"
    "Text, copied as printed (empty string if absent): \"supplier_name\" (who issued it), \"supplier_gstin\", "
    "\"supplier_pan\", \"supplier_address\" (street, city, state on one line), \"buyer_name\" and \"buyer_gstin\" "
    "(the party billed, \"bill to\"), \"buyer_address\", \"invoice_no\", \"place_of_supply\" (the state), "
    "\"payment_terms\" (for example \"Net 30\").\n"
    "Dates as YYYY-MM-DD (read the day, month and year digits carefully; a two-digit year is 20xx): \"invoice_date\", "
    "\"due_date\" (null if not printed).\n"
    "\"payment_mode\": how it was paid if the page says (\"PAID\", cash, card, UPI, bank transfer, cheque) as exactly one of "
    "\"cash\", \"card\", \"upi\", \"bank_transfer\", \"cheque\", \"credit\" (not yet paid), or null if it does not say. "
    "\"currency\": the three-letter code (INR unless the page shows another). \"expense_category\": two to five words for "
    "what this was for, such as \"Food and beverages\", \"Office rent\", \"Laptop\", \"Freight\".\n"
    "Amounts: \"taxable\" (the total taxable value before tax), \"cgst\", \"sgst\", \"igst\", \"cess\" (the total tax "
    "AMOUNTS, never the rates), \"round_off\" and \"total\" (the invoice total). Each amount is a JSON NUMBER in rupees: "
    "plain digits with a decimal point, no quotes, no currency symbol, no commas, no brackets. A negative amount has a "
    "leading minus, for example a round-off printed as (-)0.16 or -0.16 is -0.16, and one printed as 0.40 is 0.4. Use null "
    "for a tax that is not charged.\n"
    "\"items\": the invoice's lines, in order, each an object with \"description\", \"hsn_sac\" (digits, or empty), "
    "\"quantity\" (a number), \"unit\", \"rate\" (price per unit, a number), \"amount\" (the line's taxable amount, a "
    "number) and \"gst_rate\" (the GST percentage on the line, a number, or null). An empty list if there are no lines.\n"
    "Doubt: \"unsure\" is a list of the key names above that you could not read clearly or had to guess; an empty list if "
    "you are sure of everything."
)


class InvoiceVisionError(ValueError):
    """The scan could not be read; the message says what to do."""


def enabled() -> bool:
    return bool(getattr(settings, "VISION_READING", False))


def read_scanned_invoice(data: bytes, page_count: int, llm, *, client=None, page_images: list[bytes] | None = None) -> Reading:
    limit = int(settings.VISION_MAX_PAGES)
    if page_count > limit:
        raise InvoiceVisionError(f"This scan has {page_count} pages; scans are read up to {limit} pages at a time.")
    pages = page_images if page_images is not None else render_pages(data)
    started = time.monotonic()
    try:
        reply = llm.complete_json_with_images(SYSTEM, INSTRUCTION, pages, max_tokens=4096)
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
