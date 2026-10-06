"""The API refusing what it should refuse, in words a client can act on."""

from __future__ import annotations

import io

import pytest
from rest_framework.test import APIClient

from api.tests.conftest import sign_in
from classify.models import LedgerAccount, LedgerGroup
from core.db.session import firm_context
from core.models import Job

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def _upload(api, client_record, name, data, **extra):
    file = io.BytesIO(data)
    file.name = name
    return api.post(
        f"{V1}/clients/{client_record.pk}/statements/upload/",
        {"file": file, **extra},
        format="multipart",
    )


def test_a_file_that_is_not_a_pdf_is_refused_before_parsing(api, client_record):
    response = _upload(api, client_record, "statement.pdf", b"<html>not a pdf</html>")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"
    assert "not a PDF" in response.json()["fields"]["file"][0]
    assert not Job.objects.exists()  # never got as far as a job


def test_an_oversized_upload_is_refused(api, client_record, settings):
    settings.MAX_STATEMENT_UPLOAD_BYTES = 1024
    response = _upload(api, client_record, "big.pdf", b"%PDF-" + b"0" * 2048)

    assert response.status_code == 400
    assert "limit is" in response.json()["fields"]["file"][0]


def test_an_empty_upload_is_refused(api, client_record):
    response = _upload(api, client_record, "empty.pdf", b"")
    assert response.status_code == 400


def test_an_unexpected_failure_does_not_leak_its_exception(api, client_record, monkeypatch):
    """A driver error quoting a SQL statement must not come back in job.error."""
    import api.views.banking as banking_views

    def explode(**_kwargs):
        raise RuntimeError("psycopg: relation secret_table_name does not exist at /srv/app/x.py")

    monkeypatch.setattr(banking_views, "_ingest", explode)
    response = _upload(api, client_record, "s.pdf", b"%PDF-1.4 minimal")

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "FAILED"
    assert job["error_code"] == "internal_error"
    assert "secret_table_name" not in job["error"]
    assert job["id"] in job["error"]  # points at the log entry instead


def test_a_client_filter_that_is_not_a_uuid_is_a_400_not_a_500(api, client_record):
    response = api.get(f"{V1}/journal-entries/?client=not-a-uuid")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid"


def test_a_regex_rule_that_would_backtrack_forever_is_refused(api, client_record):
    with firm_context(client_record.firm_id):
        ledger = LedgerAccount.objects.create(
            firm_id=client_record.firm_id, client=client_record,
            name="Office Expenses", group=LedgerGroup.INDIRECT_EXPENSE,
        )
    response = api.post(
        f"{V1}/clients/{client_record.pk}/rules/",
        {"ledger": str(ledger.pk), "match_type": "REGEX", "pattern": "(a+)+$", "direction": "ANY"},
        format="json",
    )
    assert response.status_code == 400
    assert "exponential" in response.json()["fields"]["pattern"][0]


def test_a_malformed_regex_rule_is_refused(api, client_record):
    with firm_context(client_record.firm_id):
        ledger = LedgerAccount.objects.create(
            firm_id=client_record.firm_id, client=client_record,
            name="Office Expenses", group=LedgerGroup.INDIRECT_EXPENSE,
        )
    response = api.post(
        f"{V1}/clients/{client_record.pk}/rules/",
        {"ledger": str(ledger.pk), "match_type": "REGEX", "pattern": "(unclosed", "direction": "ANY"},
        format="json",
    )
    assert response.status_code == 400
    assert "Not a valid regex" in response.json()["fields"]["pattern"][0]


def test_a_party_gstin_is_checked_for_shape_and_check_digit(api, client_record):
    url = f"{V1}/clients/{client_record.pk}/parties/"
    bad = api.post(url, {"canonical_name": "Acme", "gstin": "27AAPFU0939F1ZW"}, format="json")
    assert bad.status_code == 400
    assert "GSTIN" in bad.json()["fields"]["gstin"][0]

    good = api.post(url, {"canonical_name": "Acme", "gstin": "27AAPFU0939F1ZV"}, format="json")
    assert good.status_code == 201
    assert good.json()["gstin"] == "27AAPFU0939F1ZV"


def test_deleting_a_ledger_with_posted_entries_is_a_409(api, client_record, statement):
    from classify.engine import review_queue

    with firm_context(client_record.firm_id):
        row = review_queue(client_record).filter(ledger__isnull=False).first()
        assert row is not None
        ledger_id = row.ledger_id
    api.post(
        f"{V1}/clients/{client_record.pk}/approvals/",
        {"classifications": [str(row.pk)]},
        format="json",
    )

    response = api.delete(f"{V1}/clients/{client_record.pk}/ledgers/{ledger_id}/")
    assert response.status_code == 409
    assert response.json()["code"] == "in_use"


def test_a_member_of_no_firm_gets_a_json_403_from_the_api(firm):
    from core.models import User

    user = User.objects.create_user(email="orphan@example.test", password="correct-horse-battery")
    http = sign_in(user)
    response = http.get(f"{V1}/clients/")
    assert response.status_code == 403
    assert response.json()["code"] == "no_firm"


def _blank_pdf(pages: int) -> bytes:
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>"]
    objects += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"] * pages
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_a_pdf_with_too_many_pages_is_refused_before_any_extraction(api, client_record, settings, monkeypatch):
    from integrations.pdf.pdfplumber_text import PdfPlumberAdapter
    from integrations.registry import reset_adapter_cache

    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "pdf": "integrations.pdf.pdfplumber_text.PdfPlumberAdapter"}
    settings.INTEGRATION_OPTIONS = {**settings.INTEGRATION_OPTIONS, "pdf": {}}
    settings.MAX_STATEMENT_PAGES = 10
    reset_adapter_cache()

    def extraction_must_not_run(self, data):
        raise AssertionError("extract() ran for a PDF over the page ceiling")

    monkeypatch.setattr(PdfPlumberAdapter, "extract", extraction_must_not_run)
    try:
        response = _upload(api, client_record, "many.pdf", _blank_pdf(11))
    finally:
        reset_adapter_cache()

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"
    assert "11 pages" in response.json()["fields"]["file"][0]
    assert not Job.objects.exists()


def test_the_api_schema_and_docs_need_a_signed_in_person():
    anonymous = APIClient()

    for path in ("/api/schema/", "/api/docs/", "/api/redoc/"):
        response = anonymous.get(path)
        assert response.status_code in (302, 401, 403), path
        assert b"openapi" not in response.content[:200].lower(), path
