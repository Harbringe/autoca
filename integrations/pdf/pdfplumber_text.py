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
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError

from .base import (
    PdfDocument,
    PdfExtractionError,
    PdfPage,
    PdfPasswordIncorrect,
    PdfPasswordRequired,
    PdfTextAdapter,
    normalise_table,
)

TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
}


def _is_password_error(exc: BaseException) -> bool:
    """pdfplumber wraps pdfminer's password failure in a generic exception; look through the wrapper."""
    seen = set()
    stack = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, PDFPasswordIncorrect):
            return True
        stack.extend(a for a in getattr(current, "args", ()) if isinstance(a, BaseException))
        for link in (current.__cause__, current.__context__):
            if link is not None:
                stack.append(link)
    return False


def _locked(password: str | None) -> PdfExtractionError:
    """The right error for a PDF that would not open: no password given, or one that did not fit."""
    if password:
        return PdfPasswordIncorrect("That password did not open the PDF. Check it and try again.")
    return PdfPasswordRequired("This PDF is password-protected. Enter its password to read it.")


class PdfPlumberAdapter(PdfTextAdapter):
    def __init__(self, **_ignored):
        pass

    def page_count(self, data: bytes, password: str | None = None) -> int:
        if not data:
            raise PdfExtractionError("Empty file: nothing to extract.")
        try:
            with pdfplumber.open(io.BytesIO(data), password=password or None) as pdf:
                return len(pdf.pages)
        except PDFPasswordIncorrect as exc:
            raise _locked(password) from exc
        except PDFSyntaxError as exc:
            raise PdfExtractionError(f"Not a readable PDF: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 -- pdfminer raises a wide variety
            if _is_password_error(exc):
                raise _locked(password) from exc
            raise PdfExtractionError(
                f"This PDF could not be read ({type(exc).__name__})."
            ) from exc

    def extract(self, data: bytes, password: str | None = None) -> PdfDocument:
        if not data:
            raise PdfExtractionError("Empty file: nothing to extract.")
        try:
            with pdfplumber.open(io.BytesIO(data), password=password or None) as pdf:
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
        except PDFPasswordIncorrect as exc:
            raise _locked(password) from exc
        except PDFSyntaxError as exc:
            raise PdfExtractionError(f"Not a readable PDF: {exc}") from exc
        except PdfExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- pdfminer raises a wide variety
            if _is_password_error(exc):
                raise _locked(password) from exc
            raise PdfExtractionError(
                "This PDF could not be read; it may be damaged or cut off. "
                f"Download it from the bank again and retry. ({type(exc).__name__}: {exc})"
            ) from exc

        return PdfDocument(engine="pdfplumber", page_count=page_count, pages=pages)
