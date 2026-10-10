"""A password-protected PDF: asked for, checked, used once, and never kept. The real PDF reader and a real locked file."""

from __future__ import annotations

import io
import pathlib

import pytest
from pypdf import PdfReader, PdfWriter

from integrations import files
from integrations.pdf.base import PdfPasswordIncorrect, PdfPasswordRequired
from integrations.pdf.pdfplumber_text import PdfPlumberAdapter

SAMPLE = pathlib.Path(__file__).resolve().parents[2] / "web" / "qa" / "samples" / "qa-api-testco-2025-04.pdf"
SECRET = "Sup3r-Secret-9137"


def locked(password: str = SECRET) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(SAMPLE.read_bytes())))
    writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_a_locked_pdf_without_its_password_asks_for_it():
    with pytest.raises(PdfPasswordRequired) as asked:
        PdfPlumberAdapter().extract(locked())
    assert "password" in str(asked.value).lower()


def test_a_wrong_password_is_its_own_error_and_does_not_repeat_what_was_typed():
    with pytest.raises(PdfPasswordIncorrect) as refused:
        PdfPlumberAdapter().extract(locked(), "not-the-password")
    assert "not-the-password" not in str(refused.value) and SECRET not in str(refused.value)


def test_the_right_password_reads_the_same_text_as_the_unlocked_file():
    plain = PdfPlumberAdapter().extract(SAMPLE.read_bytes())
    opened = PdfPlumberAdapter().extract(locked(), SECRET)
    assert opened.page_count == plain.page_count and opened.text == plain.text and opened.has_text_layer


def test_the_page_count_of_a_locked_file_needs_the_password_too():
    adapter = PdfPlumberAdapter()
    with pytest.raises(PdfPasswordRequired):
        adapter.page_count(locked())
    assert adapter.page_count(locked(), SECRET) == adapter.page_count(SAMPLE.read_bytes())


def test_the_loader_passes_the_password_through_and_leaves_the_bytes_locked():
    data = locked()
    with pytest.raises(PdfPasswordRequired):
        files.load(data, "statement.pdf")
    loaded = files.load(data, "statement.pdf", SECRET)
    assert loaded.document.has_text_layer
    # Nothing was unlocked in place: the very bytes that were handed in still need the password.
    with pytest.raises(PdfPasswordRequired):
        PdfPlumberAdapter().extract(data)


def test_a_file_that_is_not_locked_ignores_a_password_that_was_typed_anyway():
    assert PdfPlumberAdapter().extract(SAMPLE.read_bytes(), "unneeded").has_text_layer


def test_a_locked_scan_is_rendered_for_the_model_while_the_password_is_to_hand(monkeypatch):
    """No text layer and a password given: the page images are made now, so nothing later needs the password."""
    from banking import scan

    seen = {}

    def fake_render(data, **kwargs):
        seen.update(kwargs)
        return [b"png"]

    monkeypatch.setattr(scan, "render_pages", fake_render)
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(SECRET)
    out = io.BytesIO()
    writer.write(out)
    loaded = files.load(out.getvalue(), "scan.pdf", SECRET)
    assert loaded.images == [b"png"] and seen["password"] == SECRET
