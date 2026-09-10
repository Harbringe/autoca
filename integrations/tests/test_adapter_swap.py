"""Proof that the adapter boundary actually holds.

Two properties are being defended here, and they are the entire justification
for the indirection in ``integrations/``:

1.  Swapping a backend is a settings change. No business logic moves.
2.  No vendor SDK is imported outside ``integrations/``.

Property 2 is the one that rots silently. Someone adds ``import boto3`` to a
banking utility because it was quicker, and eighteen months later the "config
change" migration to AWS is a three-week refactor. The static scan below is
crude on purpose: it is cheap, it runs in CI, and it fails loudly.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from django.test import override_settings

from integrations.registry import (
    get_adapter,
    get_kms,
    get_storage,
    reset_adapter_cache,
)
from integrations.storage.base import StorageAdapter
from integrations.storage.local import LocalStorageAdapter
from integrations.storage.r2 import R2StorageAdapter
from integrations.storage.s3 import S3StorageAdapter

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Modules that only the integrations layer may import.
VENDOR_MODULES = {
    "boto3",
    "botocore",
    "redis",
    "supabase",
    "azure",
    "google.cloud",
    "openai",
    "anthropic",
}

#: Directories whose imports are checked. `integrations` is deliberately absent.
APP_PACKAGES = ("core", "banking", "ledger", "gst", "classify", "config")


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_adapter_cache()
    yield
    reset_adapter_cache()


# ---------------------------------------------------------------------------
# Property 1: the swap is a config change
# ---------------------------------------------------------------------------


def test_storage_backend_follows_configuration():
    """The same call site yields R2, S3, or local depending only on settings."""
    cases = [
        (
            "integrations.storage.r2.R2StorageAdapter",
            {"bucket": "b", "endpoint_url": "https://acct.r2.cloudflarestorage.com"},
            R2StorageAdapter,
        ),
        (
            "integrations.storage.s3.S3StorageAdapter",
            {"bucket": "b", "region": "ap-south-1"},
            S3StorageAdapter,
        ),
        (
            "integrations.storage.local.LocalStorageAdapter",
            {"root": None},
            LocalStorageAdapter,
        ),
    ]

    for dotted, options, expected in cases:
        reset_adapter_cache()
        with override_settings(
            INTEGRATIONS={**_integrations(), "storage": dotted},
            INTEGRATION_OPTIONS={**_options(), "storage": options},
        ):
            adapter = get_storage()
        assert isinstance(adapter, expected)
        assert isinstance(adapter, StorageAdapter)


def test_r2_and_s3_share_one_implementation():
    """If these ever diverge, the swap has stopped being a swap."""
    for method in ("put", "get", "delete", "exists", "presigned_url"):
        assert getattr(R2StorageAdapter, method) is getattr(S3StorageAdapter, method), (
            f"{method}() differs between the R2 and S3 adapters. They must both "
            f"inherit it from S3CompatibleStorageAdapter, or the AWS migration is "
            f"no longer a configuration change."
        )


def test_registry_rejects_a_class_that_does_not_implement_the_interface():
    from django.core.exceptions import ImproperlyConfigured

    with override_settings(
        INTEGRATIONS={**_integrations(), "storage": "core.models.Firm"}
    ):
        with pytest.raises(ImproperlyConfigured, match="not a subclass"):
            get_adapter("storage")


def test_every_configured_adapter_resolves():
    """Each of the five kinds must load with the settings as shipped."""
    for kind in ("storage", "ocr", "queue", "kms", "llm"):
        assert get_adapter(kind) is not None


# ---------------------------------------------------------------------------
# Property 2: vendor SDKs stay behind the boundary
# ---------------------------------------------------------------------------


def test_no_vendor_sdk_imported_outside_integrations():
    offenders = []

    for package in APP_PACKAGES:
        for path in (REPO_ROOT / package).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    root = name.split(".")[0]
                    if root in VENDOR_MODULES or name in VENDOR_MODULES:
                        rel = path.relative_to(REPO_ROOT)
                        offenders.append(f"{rel}:{node.lineno} imports {name}")

    assert not offenders, (
        "Vendor SDKs must only be imported inside integrations/. Move these behind "
        "an adapter:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Envelope encryption round-trip, and its tenant binding
# ---------------------------------------------------------------------------


def test_envelope_round_trip():
    from core.crypto import decrypt_text_for_firm, encrypt_for_firm

    firm_id = "11111111-1111-1111-1111-111111111111"
    blob = encrypt_for_firm("PAN ABCDE1234F", firm_id, purpose="test")

    assert b"ABCDE1234F" not in blob
    assert decrypt_text_for_firm(blob, firm_id, purpose="test") == "PAN ABCDE1234F"


def test_ciphertext_is_bound_to_its_firm():
    """A blob encrypted for firm A must not decrypt in firm B's context.

    This is the cryptographic half of tenant isolation. RLS stops the wrong rows
    being read; this stops the wrong bytes being understood even if they are.
    """
    from core.crypto import decrypt_for_firm, encrypt_for_firm
    from integrations.kms.base import EnvelopeError

    blob = encrypt_for_firm("secret", "11111111-1111-1111-1111-111111111111")

    with pytest.raises(EnvelopeError):
        decrypt_for_firm(blob, "22222222-2222-2222-2222-222222222222")


def test_ciphertext_is_bound_to_its_purpose():
    from core.crypto import decrypt_for_firm, encrypt_for_firm
    from integrations.kms.base import EnvelopeError

    firm_id = "11111111-1111-1111-1111-111111111111"
    blob = encrypt_for_firm("secret", firm_id, purpose="banking")

    with pytest.raises(EnvelopeError):
        decrypt_for_firm(blob, firm_id, purpose="gst")


def test_tampering_is_detected():
    from core.crypto import encrypt_for_firm
    from integrations.kms.base import EnvelopeError

    firm_id = "11111111-1111-1111-1111-111111111111"
    blob = bytearray(encrypt_for_firm("secret", firm_id))
    blob[-1] ^= 0xFF

    with pytest.raises(EnvelopeError):
        get_kms().decrypt(bytes(blob), {"firm_id": firm_id, "purpose": "generic"})


def test_each_ciphertext_uses_a_fresh_data_key():
    from core.crypto import encrypt_for_firm

    firm_id = "11111111-1111-1111-1111-111111111111"
    a = encrypt_for_firm("same plaintext", firm_id)
    b = encrypt_for_firm("same plaintext", firm_id)
    assert a != b


# ---------------------------------------------------------------------------
# Storage key discipline
# ---------------------------------------------------------------------------


def test_object_keys_are_firm_prefixed():
    key = StorageAdapter.tenant_key("11111111-1111-1111-1111-111111111111", "statements", "x.pdf")
    assert key == "firms/11111111-1111-1111-1111-111111111111/statements/x.pdf"


def test_a_key_from_another_firm_is_refused():
    key = StorageAdapter.tenant_key("11111111-1111-1111-1111-111111111111", "x.pdf")
    with pytest.raises(PermissionError):
        StorageAdapter.verify_tenant_key(key, "22222222-2222-2222-2222-222222222222")


def test_local_storage_refuses_path_traversal(tmp_path):
    adapter = LocalStorageAdapter(root=str(tmp_path))
    with pytest.raises(PermissionError):
        adapter.get("../../etc/passwd")


# ---------------------------------------------------------------------------
# OCR: the F0 truncation trap
# ---------------------------------------------------------------------------


def test_partial_ocr_result_cannot_be_constructed():
    """A truncating OCR tier must not be able to return a plausible result.

    Azure Document Intelligence F0 silently processes only the first two pages.
    This is the structural defence against a future adapter reintroducing that
    failure mode.
    """
    from integrations.ocr.base import OCRPage, OCRResult, OCRTruncationError

    with pytest.raises(OCRTruncationError):
        OCRResult(
            engine="azure-di-f0",
            page_count=14,
            pages_processed=2,
            pages=[OCRPage(page_number=1, text="...")],
        )


def test_ocr_stub_refuses_rather_than_returning_empty_text():
    from integrations.ocr.stub import StubOCRAdapter

    with pytest.raises(NotImplementedError):
        StubOCRAdapter().extract(b"%PDF-1.4")


# ---------------------------------------------------------------------------


def _integrations():
    from django.conf import settings

    return dict(settings.INTEGRATIONS)


def _options():
    from django.conf import settings

    return {k: dict(v) for k, v in settings.INTEGRATION_OPTIONS.items()}
