"""Parser registry: document in, proved statement out.

Two tiers, and the ordering is the point.

**Dedicated parsers** know one bank's layout exactly. They are worth writing
when a format defeats inference, or to pick up detail the generic path drops.
They are an optimisation, not a requirement.

**The generic parser** reads any ruled transaction table by inferring which
column is which and proving the inference against the statement's own running
balance. It is what makes "works with whatever bank the client uses" true
rather than aspirational -- a firm with thirty clients sees a dozen banks, and
waiting for someone to write a parser for each is waiting forever.

Detection is by content, never by filename or by a field the uploader picked. A
firm's staff will upload the wrong bank's statement eventually, and a
mis-declared format that parses anyway is how a client's year gets silently
misstated. Two dedicated parsers claiming one document is an error rather than
first-match-wins, because it means one of their detectors is too loose.
"""

from __future__ import annotations

from integrations.pdf.base import PdfDocument

from .axis import AxisStatementParser
from .base import (
    BalanceChainError,
    NoTextLayerError,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
    StatementParser,
    UnsupportedBankError,
)
from .generic import GenericStatementParser

#: Tried first, in order. Each must recognise only its own bank.
DEDICATED_PARSERS: tuple[type[StatementParser], ...] = (AxisStatementParser,)

#: Tried when no dedicated parser claims the document.
FALLBACK_PARSER: type[StatementParser] = GenericStatementParser

PARSERS: tuple[type[StatementParser], ...] = (*DEDICATED_PARSERS, FALLBACK_PARSER)

__all__ = [
    "DEDICATED_PARSERS",
    "FALLBACK_PARSER",
    "PARSERS",
    "BalanceChainError",
    "NoTextLayerError",
    "ParsedStatement",
    "ParsedTransaction",
    "StatementParseError",
    "StatementParser",
    "UnsupportedBankError",
    "detect_parser",
    "parse_statement",
]


def detect_parser(document: PdfDocument) -> StatementParser:
    if not document.has_text_layer:
        raise NoTextLayerError(
            "This PDF has no text layer, so it is a scan. OCR is the fallback "
            "path for scanned statements and is not wired yet -- see "
            "integrations/ocr/base.py before reaching for a vendor."
        )

    matches = [parser for parser in DEDICATED_PARSERS if parser.detect(document)]
    if len(matches) > 1:
        raise UnsupportedBankError(
            f"{len(matches)} parsers claim this document "
            f"({', '.join(p.bank_code for p in matches)}). One of their detectors "
            f"is too loose; guessing between them would be worse than refusing."
        )
    if matches:
        return matches[0]()

    if FALLBACK_PARSER.detect(document):
        return FALLBACK_PARSER()

    raise UnsupportedBankError(
        "Nothing in this document looks like a transaction table: no page has "
        "rows carrying a date and two amounts. If the statement is a scan, it "
        "needs OCR; if its table has no ruled borders, the extractor found no "
        "cells to read."
    )


def parse_statement(document: PdfDocument) -> ParsedStatement:
    """Detect the format and parse. Raises rather than returning a doubtful read."""
    return detect_parser(document).parse(document)
