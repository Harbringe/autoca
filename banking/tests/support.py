"""Test helpers shared by the banking and classification suites.

The fixture adapter is here rather than in a conftest because it is selected by
dotted path in settings, and a conftest module is an awkward thing to name in a
settings value.
"""

from __future__ import annotations

import datetime
import json

import pytest

from banking.tests.conftest import FIXTURES
from integrations.pdf.base import PdfDocument, PdfTextAdapter

AXIS_FIXTURE = json.loads((FIXTURES / "axis_savings_statement.json").read_text(encoding="utf-8"))

#: What the redacted fixture says about the account it belongs to.
ACCOUNT_NUMBER = "911010000004321"
ACCOUNT_HOLDER = "RAMESH GOPAL DESHMUKH"
TRANSACTION_COUNT = 54


class FixturePdfAdapter(PdfTextAdapter):
    """Returns the captured Axis statement whatever bytes it is handed.

    The input bytes still matter to the code under test: they are what the
    content hash and the stored object are built from.
    """

    def __init__(self, **_ignored):
        pass

    def extract(self, data: bytes) -> PdfDocument:
        return PdfDocument.from_dict(AXIS_FIXTURE)


@pytest.fixture
def fixture_adapters(tmp_path, settings):
    """Point the pdf and storage adapters at the fixture and a temp directory."""
    from integrations.registry import reset_adapter_cache

    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": "banking.tests.support.FixturePdfAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {
        **settings.INTEGRATION_OPTIONS,
        "pdf": {},
        "storage": {"root": str(tmp_path / "storage")},
    }
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def ingest_fixture_statement(client, data: bytes = b"%PDF-1.4 axis", filename: str = "axis.pdf"):
    """Ingest the captured statement for ``client``. Caller supplies the context."""
    from banking.ingest import ingest_statement

    return ingest_statement(client=client, data=data, filename=filename)


FY_START = datetime.date(2025, 4, 1)
