"""pdfplumber-backed text and table extraction.

pdfplumber sits on pdfminer.six and runs entirely in-process -- there is no
service, no key, and no per-page cost. It is behind an adapter anyway so that
swapping to PyMuPDF (faster, AGPL) or a hosted extractor stays one file.

Table strategy is ``lines``: cells are found from the ruling the bank actually
drew, not inferred from whitespace. Whitespace inference guesses wrong on the
exact rows that matter -- a blank Debit cell and a blank Credit cell look
identical to a column-position heuristic, and the amount lands in whichever one
the heuristic prefers.
"""

from __future__ import annotations

import io

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

from .base import PdfDocument, PdfExtractionError, PdfPage, PdfTextAdapter, normalise_table

TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
}


class PdfPlumberAdapter(PdfTextAdapter):
    def __init__(self, **_ignored):
        pass

    def extract(self, data: bytes) -> PdfDocument:
        if not data:
            raise PdfExtractionError("Empty file: nothing to extract.")
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = tuple(
                    PdfPage(
                        page_number=number,
                        text=page.extract_text() or "",
                        tables=tuple(
                            normalise_table(table)
                            for table in page.extract_tables(TABLE_SETTINGS)
                        ),
                    )
                    for number, page in enumerate(pdf.pages, start=1)
                )
                page_count = len(pdf.pages)
        except PDFSyntaxError as exc:
            raise PdfExtractionError(f"Not a readable PDF: {exc}") from exc
        except PdfExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- pdfminer raises a wide variety
            raise PdfExtractionError(f"Could not extract this PDF: {exc}") from exc

        return PdfDocument(engine="pdfplumber", page_count=page_count, pages=pages)
