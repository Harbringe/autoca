"""Stub OCR adapter -- the only OCR backend wired in this phase.

It raises. That is intentional: an adapter that returned empty text would let
document-handling code appear to work while producing nothing, and this codebase
prefers loud failure at every isolation and correctness boundary.

The interface is real, so when a paid Azure DI S0 or Google Document AI adapter
lands, the call sites already exist and do not change.
"""

from .base import OCRAdapter, OCRResult


class StubOCRAdapter(OCRAdapter):
    def __init__(self, **_ignored):
        pass

    def extract(self, data, mime_type="application/pdf"):
        raise NotImplementedError(
            "No OCR backend is wired. OCR is the fallback path for scanned "
            "documents and is deliberately not implemented in the scaffold "
            "phase. See integrations/ocr/base.py for why Azure DI F0 must not "
            "be used to fill this gap."
        )


__all__ = ["StubOCRAdapter", "OCRResult"]
