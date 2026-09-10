"""OCR interface.

Read this before wiring any real OCR vendor.

OCR is the *fallback* path in this system, not the default. Most bank statement
PDFs a CA firm receives are born-digital and carry a real text layer; the right
first move is text-layer extraction, and OCR is for the scanned minority. That
ordering is a correctness decision as much as a cost one -- extracted text is
exact, OCR output is a guess with a confidence score.

DO NOT wire Azure Document Intelligence's free F0 tier.
    F0 allows 500 pages/month, but processes only the FIRST TWO PAGES of any
    document and drops the rest **without raising an error**. Bank statements
    are rarely one or two pages. Testing against F0 produces results that are
    quietly incomplete and look successful, which is worse than a hard failure
    because nothing in the pipeline can detect it. Google Document AI has no
    equivalent standing free tier -- what looks like one is expiring GCP trial
    credit, not a renewing monthly allowance.

    When real OCR is needed, buy a small Azure DI S0 batch or Document AI usage
    and write the adapter then.

The ``page_count`` and ``pages_processed`` fields on :class:`OCRResult` exist
specifically so that a truncating tier can never pass silently again:
``OCRResult.__post_init__`` refuses to construct a result where they disagree.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


class OCRTruncationError(RuntimeError):
    """An OCR backend returned fewer pages than the document contains."""


@dataclass(frozen=True)
class OCRPage:
    page_number: int
    text: str
    confidence: float = 0.0


@dataclass(frozen=True)
class OCRResult:
    engine: str
    page_count: int
    pages_processed: int
    pages: list[OCRPage] = field(default_factory=list)

    def __post_init__(self):
        if self.pages_processed != self.page_count:
            raise OCRTruncationError(
                f"{self.engine} processed {self.pages_processed} of "
                f"{self.page_count} pages. Refusing to return a partial result: "
                f"silently truncated OCR is indistinguishable from a clean read "
                f"downstream."
            )

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)


class OCRAdapter(abc.ABC):
    @abc.abstractmethod
    def extract(self, data: bytes, mime_type: str = "application/pdf") -> OCRResult:
        ...

    @property
    def name(self) -> str:
        return type(self).__name__
