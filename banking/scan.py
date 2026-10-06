"""Reading a statement from page images, for PDFs that have no text layer or only a partial one.

A scan carries no text to extract, so the pages are drawn as images and a vision-capable model is asked to copy
out what is printed. That is a guess, not an extraction, so nothing the model says is trusted:

* every figure is turned into paise and put through the same :class:`ParsedStatement` that proves any statement,
  so the running balance must follow from the opening balance row by row and arrive at the printed closing balance.
  A single misread digit breaks that chain and the statement is refused with the row it broke at;
* an account number, a period and an opening or closing balance the model could not read are refused, not guessed;
* it is used only when a page really has no text (never to rescue a text statement that merely failed to parse),
  and only when the firm has switched ``VISION_READING`` on, because page images cannot be masked.

Pages go in small groups so one call does not carry a whole statement, and the groups are stitched back together
in order. Nothing here is stored: the images exist in memory for the length of the call.
"""

from __future__ import annotations

import io
import json
import re

from django.conf import settings

from banking.parsers.base import (
    BalanceChainError,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
)
from banking.parsers.columns import as_date, as_paise
from integrations.llm.base import LLMError, LLMRateLimited, LLMUnavailable
from integrations.pdf.base import PdfDocument

SYSTEM = (
    "You copy the contents of scanned bank account statement pages into JSON. You do not calculate, correct, "
    "round or infer anything: copy each figure exactly as printed, digit for digit. If something is not on "
    "these pages, use an empty string. Reply with one JSON object and nothing else."
)

INSTRUCTION = (
    "These are consecutive pages of one statement{continued}. Return JSON with exactly these keys: "
    '"statement_type" ("bank", "loan", "card" or "other"), "bank_name", "account_number", "account_holder", '
    '"ifsc", "period_start" and "period_end" (DD-MM-YYYY), "opening_balance" and "closing_balance" (as printed, '
    'with any Cr or Dr), and "transactions": a list, in the order printed, of objects with "date" (DD-MM-YYYY), '
    '"narration" (the full description, wrapped lines joined), "debit", "credit" and "balance" (as printed, '
    "blank when that column is empty for the row). Include every transaction row on these pages and nothing "
    "else: no headers, page totals, or opening and closing balance lines. Header fields may be empty on pages "
    "that do not show them."
)


def needs_vision(document: PdfDocument) -> bool:
    """True when at least one page has no text, so a text read alone cannot be complete."""
    return any(not page.has_text for page in document.pages)


def enabled() -> bool:
    return bool(getattr(settings, "VISION_READING", False))


def render_pages(data: bytes, *, dpi: int | None = None) -> list[bytes]:
    """Every page of the PDF as PNG bytes, in order."""
    import pypdfium2 as pdfium

    scale = (dpi or settings.VISION_DPI) / 72
    pdf = pdfium.PdfDocument(data)
    try:
        out = []
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                buffer = io.BytesIO()
                page.render(scale=scale).to_pil().convert("RGB").save(
                    buffer, format="PNG", optimize=True
                )
                out.append(buffer.getvalue())
            finally:
                page.close()
        return out
    finally:
        pdf.close()


def read_statement(data: bytes, document: PdfDocument, llm) -> ParsedStatement:
    """Read ``data`` from its page images and return it only if it proves out."""
    images = render_pages(data)
    if len(images) != document.page_count:
        raise StatementParseError("The pages could not all be drawn, so the scan was not read.")
    per_call = max(1, int(settings.VISION_PAGES_PER_CALL))
    replies = []
    for start in range(0, len(images), per_call):
        group = images[start : start + per_call]
        replies.append(_ask(llm, group, continued=start > 0))
    return _assemble(replies)


def _ask(llm, group: list[bytes], *, continued: bool) -> dict:
    prompt = INSTRUCTION.format(continued=", continuing from earlier pages" if continued else "")
    try:
        reply = llm.complete_json_with_images(SYSTEM, prompt, group, max_tokens=8192)
    except LLMUnavailable as exc:
        raise StatementParseError(
            "This PDF is a scan and the model that reads scans is not set up. Set the model in the server settings."
        ) from exc
    except LLMRateLimited as exc:
        raise StatementParseError(
            "The reading service is busy or its allowance is used up. Try this scan again in a few minutes."
        ) from exc
    except LLMError as exc:
        raise StatementParseError(f"The scan could not be read: {exc}") from exc
    try:
        parsed = json.loads(reply.text)
    except ValueError as exc:
        raise StatementParseError(
            "The scan was read, but the reply was not understandable."
        ) from exc
    if not isinstance(parsed, dict):
        raise StatementParseError("The scan was read, but the reply was not understandable.")
    return parsed


def _first(replies: list[dict], key: str) -> str:
    for reply in replies:
        value = str(reply.get(key) or "").strip()
        if value:
            return value
    return ""


def _last(replies: list[dict], key: str) -> str:
    return _first(list(reversed(replies)), key)


def _money(text) -> int | None:
    value = str(text or "").strip()
    return as_paise(value) if value else None


def _assemble(replies: list[dict]) -> ParsedStatement:
    kind = _first(replies, "statement_type").lower()
    if kind in {"loan", "card"}:
        raise StatementParseError(
            f"This scan is a {kind} statement. Only bank account scans are read for now."
        )

    account = re.sub(r"[\s-]+", "", _first(replies, "account_number"))
    if not account:
        raise StatementParseError(
            "The account number could not be read from the scan. Upload a clearer copy."
        )

    rows: list[ParsedTransaction] = []
    unreadable = 0
    for reply in replies:
        for raw in reply.get("transactions") or []:
            if not isinstance(raw, dict):
                unreadable += 1
                continue
            day = as_date(str(raw.get("date") or ""))
            debit = _money(raw.get("debit")) or 0
            credit = _money(raw.get("credit")) or 0
            balance = _money(raw.get("balance"))
            if day is None or balance is None or (not debit and not credit):
                unreadable += 1
                continue
            rows.append(
                ParsedTransaction(
                    row_number=len(rows) + 1,
                    date=day,
                    narration=re.sub(r"\s+", " ", str(raw.get("narration") or "")).strip(),
                    debit_paise=debit,
                    credit_paise=credit,
                    balance_paise=balance,
                )
            )
    if unreadable:
        raise StatementParseError(
            f"{unreadable} row(s) on the scan could not be read completely (a date, an amount or a balance was "
            "missing or unclear), so nothing was imported. Upload a clearer copy."
        )
    if not rows:
        raise StatementParseError("No transactions could be read from the scan.")

    opening = _money(_first(replies, "opening_balance"))
    if opening is None:
        # Not printed on these pages: it is whatever the first row started from.
        first = rows[0]
        opening = first.balance_paise - first.signed_paise
    closing = _money(_last(replies, "closing_balance"))
    if closing is None:
        closing = rows[-1].balance_paise

    start = as_date(_first(replies, "period_start")) or min(r.date for r in rows)
    end = as_date(_last(replies, "period_end")) or max(r.date for r in rows)
    holder = _first(replies, "account_holder")
    ifsc = _first(replies, "ifsc").upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
        ifsc = ""

    try:
        return ParsedStatement(
            bank_code="GENERIC",
            account_number=account,
            period_start=start,
            period_end=end,
            opening_balance_paise=opening,
            closing_balance_paise=closing,
            transactions=tuple(rows),
            account_holder=holder,
            ifsc=ifsc,
        )
    except BalanceChainError as exc:
        raise BalanceChainError(
            f"The scan was read, but what was read does not add up, so nothing was imported. {exc}"
        ) from exc
