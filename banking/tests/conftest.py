"""Shared fixtures for the banking suite.

``axis_document`` is a redacted capture of a real 3-page Axis savings statement
covering FY2025-26. Every amount, date, row order and narration *shape* is the
bank's own; the account number, holder, related-party names, PAN, address and
card digits are substituted. That combination is deliberate -- the parser is
tested against genuine layout quirks (a table that continues across a page
without repeating its header, narration wrapped mid-token, three summary rows
mixed in with the transactions) without the repository carrying a real person's
financial records.

The capture is of the *extractor's output*, not of the PDF. Extraction is
pdfplumber's job and is covered in ``integrations/tests``; what is worth testing
exhaustively here is everything above it.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from integrations.pdf.base import PdfDocument

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

#: A real statement can be dropped here to run the parser against it end to end.
#: Gitignored, and the tests that use it skip when it is absent.
SAMPLES = pathlib.Path(__file__).resolve().parents[2] / ".devdata" / "samples"


def load_document(name: str) -> PdfDocument:
    return PdfDocument.from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


@pytest.fixture
def axis_document() -> PdfDocument:
    return load_document("axis_savings_statement.json")
