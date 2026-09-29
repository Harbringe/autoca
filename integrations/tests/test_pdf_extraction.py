"""The PDF text-layer adapter and its anti-truncation gate."""

from __future__ import annotations

import pathlib

import pytest
from django.test import override_settings

from integrations.pdf.base import (
    PdfDocument,
    PdfExtractionError,
    PdfPage,
    PdfTextAdapter,
    PdfTruncationError,
)
from integrations.pdf.pdfplumber_text import PdfPlumberAdapter
from integrations.registry import get_pdf

#: Drop a real statement here to exercise extraction end to end. Gitignored;
#: these tests skip when it is absent, so CI never depends on client data.
SAMPLES = pathlib.Path(__file__).resolve().parents[2] / ".devdata" / "samples"


def test_the_pdf_backend_follows_configuration():
    with override_settings(
        INTEGRATIONS={"pdf": "integrations.pdf.pdfplumber_text.PdfPlumberAdapter"},
        INTEGRATION_OPTIONS={"pdf": {}},
    ):
        assert isinstance(get_pdf(), PdfPlumberAdapter)
        assert isinstance(get_pdf(), PdfTextAdapter)


def test_a_document_that_lost_pages_refuses_to_exist():
    """The Azure F0 failure mode, closed off in the type rather than in a check.

    A backend that returns the first two pages of a twelve-page statement
    produces output that looks clean and balances to the wrong closing figure.
    See integrations/ocr/base.py for the history behind this.
    """
    with pytest.raises(PdfTruncationError, match="2 of 12 pages"):
        PdfDocument(
            engine="truncating-backend",
            page_count=12,
            pages=(PdfPage(page_number=1), PdfPage(page_number=2)),
        )


def test_a_scan_reports_no_text_layer_rather_than_failing():
    """Routing to OCR is the caller's decision, so this is a question, not an error."""
    scan = PdfDocument(engine="t", page_count=1, pages=(PdfPage(page_number=1, text="   "),))
    digital = PdfDocument(engine="t", page_count=1, pages=(PdfPage(page_number=1, text="Axis"),))

    assert not scan.has_text_layer
    assert digital.has_text_layer


def test_documents_round_trip_through_their_serialised_form():
    """Parser fixtures are stored this way, so the round trip has to be exact."""
    original = PdfDocument(
        engine="t",
        page_count=1,
        pages=(
            PdfPage(
                page_number=1,
                text="Tran Date Particulars",
                tables=((("Tran Date", "Debit"), ("13-04-2025", "250.00")),),
            ),
        ),
    )

    assert PdfDocument.from_dict(original.to_dict()) == original


def test_empty_cells_normalise_to_strings():
    """pdfplumber reports an absent cell as None. Callers never handle it."""
    page = PdfPage.from_dict({"page_number": 1, "tables": [[["13-04-2025", None, "250.00"]]]})

    assert page.tables[0][0] == ("13-04-2025", "", "250.00")


def test_something_that_is_not_a_pdf_is_refused():
    with pytest.raises(PdfExtractionError):
        PdfPlumberAdapter().extract(b"this is not a pdf")


def test_an_empty_upload_is_refused():
    with pytest.raises(PdfExtractionError, match="Empty file"):
        PdfPlumberAdapter().extract(b"")


@pytest.mark.parametrize("sample", sorted(SAMPLES.glob("*.pdf")) if SAMPLES.exists() else [])
def test_real_statements_extract_and_parse(sample):
    """Opt-in: runs only against PDFs a developer dropped into .devdata/samples.

    This is the one test that exercises pdfplumber against a genuine file. The
    rest of the suite works from a captured, redacted extraction so that CI
    never needs a client's bank statement to run.
    """
    from banking.parsers import parse_statement

    document = PdfPlumberAdapter().extract(sample.read_bytes())
    assert document.has_text_layer

    statement = parse_statement(document)
    assert len(statement) > 0


def test_page_count_reads_the_page_tree_without_extracting():
    from api.tests.test_hardening import _blank_pdf

    assert PdfPlumberAdapter().page_count(_blank_pdf(7)) == 7
    with pytest.raises(PdfExtractionError):
        PdfPlumberAdapter().page_count(b"")
    with pytest.raises(PdfExtractionError):
        PdfPlumberAdapter().page_count(b"%PDF-1.4 not really")
