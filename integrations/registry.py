"""Adapter resolution.

This is the only place in the codebase that decides which concrete external
service is in play. Business logic asks for ``get_storage()`` and receives
something implementing ``StorageAdapter``; it never learns whether that is
Cloudflare R2 today or AWS S3 at beta.

The rule this enforces, and that ``integrations/tests/test_adapter_swap.py``
verifies: changing a backend is a change to settings/env and the addition of one
file under ``integrations/<kind>/``. Nothing outside that directory moves.
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from integrations.kms.base import KMSAdapter
from integrations.llm.base import LLMAdapter
from integrations.ocr.base import OCRAdapter
from integrations.pdf.base import PdfTextAdapter
from integrations.queue.base import QueueAdapter
from integrations.storage.base import StorageAdapter

INTERFACES = {
    "storage": StorageAdapter,
    "ocr": OCRAdapter,
    "pdf": PdfTextAdapter,
    "queue": QueueAdapter,
    "kms": KMSAdapter,
    "llm": LLMAdapter,
}

_cache: dict[str, object] = {}
_lock = threading.Lock()


def get_adapter(kind: str):
    """Return the configured adapter instance for ``kind``, memoised per process."""
    if kind not in INTERFACES:
        raise ImproperlyConfigured(
            f"Unknown integration {kind!r}. Known kinds: {sorted(INTERFACES)}"
        )

    dotted = settings.INTEGRATIONS.get(kind)
    if not dotted:
        raise ImproperlyConfigured(f"settings.INTEGRATIONS['{kind}'] is not set.")

    cache_key = f"{kind}:{dotted}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    with _lock:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            cls = import_string(dotted)
        except ImportError as exc:
            raise ImproperlyConfigured(
                f"Could not import {kind} adapter {dotted!r}: {exc}"
            ) from exc

        expected = INTERFACES[kind]
        if not (isinstance(cls, type) and issubclass(cls, expected)):
            raise ImproperlyConfigured(
                f"{dotted} is not a subclass of {expected.__name__}. Every {kind} "
                f"adapter must implement that interface so callers stay portable."
            )

        options = dict(settings.INTEGRATION_OPTIONS.get(kind, {}))
        instance = cls(**options) if options else cls()
        _cache[cache_key] = instance
        return instance


def reset_adapter_cache() -> None:
    """Drop memoised adapters. Used by tests that override settings."""
    with _lock:
        _cache.clear()


def get_storage() -> StorageAdapter:
    return get_adapter("storage")


def get_ocr() -> OCRAdapter:
    return get_adapter("ocr")


def get_pdf() -> PdfTextAdapter:
    return get_adapter("pdf")


def get_queue() -> QueueAdapter:
    return get_adapter("queue")


def get_kms() -> KMSAdapter:
    return get_adapter("kms")


def get_llm() -> LLMAdapter:
    return get_adapter("llm")
