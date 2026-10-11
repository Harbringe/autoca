"""Which GET/HEAD paths count as a sensitive read -- decrypting or rendering something that deserves a record even
though nothing was written. Pure: no database, no HTTP; see api/tests/test_audit_reads.py for the end-to-end proof.
"""

from __future__ import annotations

import pytest

from core.middleware.audit import SENSITIVE_READS

DOC_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/documents/{DOC_ID}/download/",
        f"/api/v1/clients/{DOC_ID}/bank-accounts/{DOC_ID}/",
        f"/api/v1/documents/{DOC_ID}/preview/",
        f"/api/v1/documents/{DOC_ID}/preview/1/",
        f"/api/v1/documents/{DOC_ID}/preview/42/",
    ],
)
def test_a_sensitive_read_matches_one_of_the_patterns(path):
    assert any(p.fullmatch(path) for p in SENSITIVE_READS)


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/documents/{DOC_ID}/",
        f"/api/v1/documents/{DOC_ID}/preview/abc/",  # not a page number
        "/api/v1/documents/",
    ],
)
def test_an_ordinary_read_matches_none_of_the_patterns(path):
    assert not any(p.fullmatch(path) for p in SENSITIVE_READS)
