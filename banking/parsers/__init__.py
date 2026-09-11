"""Parser registry: document in, proved statement out.

Detection is by content, not by filename or by a field the uploader picked.
A firm's staff will upload the wrong bank's statement eventually, and a
mis-declared format that parses anyway is how a client's year gets silently
misstated. Two parsers claiming the same document is also an error rather than
a first-match-wins, because it means one of the detectors is too loose.
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

PARSERS: tuple[type[StatementParser], ...] = (AxisStatementParser,)

__all__ = [
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

    matches = [parser for parser in PARSERS if parser.detect(document)]
    if not matches:
        raise UnsupportedBankError(
            f"No parser recognised this statement. Supported formats: "
            f"{', '.join(p.bank_code for p in PARSERS)}."
        )
    if len(matches) > 1:
        raise UnsupportedBankError(
            f"{len(matches)} parsers claim this document "
            f"({', '.join(p.bank_code for p in matches)}). One of their detectors "
            f"is too loose; guessing between them would be worse than refusing."
        )
    return matches[0]()


def parse_statement(document: PdfDocument) -> ParsedStatement:
    """Detect the format and parse. Raises rather than returning a doubtful read."""
    return detect_parser(document).parse(document)
