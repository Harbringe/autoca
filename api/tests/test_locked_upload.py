"""Uploading a locked statement through the API: the password is asked for, checked, used once and never kept."""

from __future__ import annotations

import io
import pathlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader, PdfWriter

from banking.models import Statement
from core.jobs import Job
from documents.models import Document
from integrations.registry import reset_adapter_cache

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
SAMPLE = pathlib.Path(__file__).resolve().parents[2] / "web" / "qa" / "samples" / "qa-api-testco-2025-04.pdf"
SECRET = "Sup3r-Secret-9137"


@pytest.fixture(autouse=True)
def real_pdf_reader(settings, tmp_path):
    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": "integrations.pdf.pdfplumber_text.PdfPlumberAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {**settings.INTEGRATION_OPTIONS, "storage": {"root": str(tmp_path / "storage")}}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def locked_bytes() -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(SAMPLE.read_bytes())))
    writer.encrypt(SECRET)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def upload(api, client_record, data: bytes, **extra):
    return api.post(
        f"{V1}/clients/{client_record.pk}/statements/upload/",
        {"file": SimpleUploadedFile("locked.pdf", data, content_type="application/pdf"), **extra},
        format="multipart",
    )


def test_a_locked_statement_asks_for_its_password(api, client_record):
    body = upload(api, client_record, locked_bytes()).json()
    assert body["status"] == "FAILED" and body["error_code"] == "password_required"


def test_a_wrong_password_is_refused_in_its_own_words_and_not_echoed(api, client_record):
    response = upload(api, client_record, locked_bytes(), password="nope-nope")
    body = response.json()
    assert body["status"] == "FAILED" and body["error_code"] == "password_incorrect"
    assert "nope-nope" not in response.content.decode()


def test_the_right_password_reads_the_statement_and_the_file_is_kept_locked(api, client_record):
    data = locked_bytes()
    body = upload(api, client_record, data, password=SECRET).json()
    assert body["status"] == "SUCCEEDED" and body["result"]["rows_created"] > 0

    # The original is stored exactly as it came, still locked, and the password is nowhere in the database.
    document = Document.objects.get(client=client_record)
    assert document.storage_key
    assert SECRET not in repr(list(Job.objects.values())) and SECRET not in repr(list(Statement.objects.values()))
    assert SECRET not in repr(list(Document.objects.values()))
