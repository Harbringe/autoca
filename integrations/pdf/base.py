"""Text-layer extraction from born-digital PDFs.

This is the *default* document path, and OCR (``integrations/ocr/``) is the
fallback for the scanned minority. The ordering is a correctness decision, not
a cost one: a text layer is the exact bytes the bank's own renderer emitted,
while OCR output is a guess with a confidence score attached.

Bank statements are ruled tables, and every mainstream Indian bank's PDF draws
real table borders. That means a table extractor can recover the Debit and
Credit columns as *separate cells*, which matters more than it sounds like it
should: flattened to a line of text, a row reads

    13-04-2025  Sweep/VO000000012345678/...  250.00  112500.00  318

and nothing in that string says whether ``250.00`` was money in or money out.
So this interface exposes cells, not just text, and the parsers above it never
have to guess a column from an amount's position in a sentence.

Two failure modes are closed off structurally rather than by convention:

* :class:`PdfDocument` refuses to exist when ``pages`` and ``page_count``
  disagree, for the same reason :class:`~integrations.ocr.base.OCRResult` does.
  A backend that silently drops pages past the first two produces results that
  look clean and are wrong, and nothing downstream can tell.
* ``has_text_layer`` is a question the caller must ask before trusting the
  output. A scanned PDF extracts to empty strings, not to an error, so the only
  thing standing between a scan and a "successfully parsed, zero transactions"
  statement is an explicit check.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


class PdfExtractionError(RuntimeError):
    """The PDF could not be read at all -- corrupt, encrypted, or not a PDF."""


class PdfTruncationError(PdfExtractionError):
    """A backend returned fewer pages than the document contains."""


class PdfPasswordRequired(PdfExtractionError):
    """The PDF is locked and no password was given. The person is asked for it; it is never guessed."""


class PdfPasswordIncorrect(PdfExtractionError):
    """A password was given and it did not open the PDF. Neither the password nor the file's contents are in the message."""


#: One extracted table: rows of cells. A cell that the backend reported as
#: empty or absent is normalised to ``""`` so callers never handle ``None``.
PdfTable = tuple[tuple[str, ...], ...]


def normalise_table(rows) -> PdfTable:
    """Coerce a backend's nested lists into an immutable table of strings."""
    return tuple(tuple("" if cell is None else str(cell) for cell in row) for row in rows)


@dataclass(frozen=True)
class PdfWord:
    """One word and where it sits on the page, in points from the page's left edge."""

    text: str
    x0: float
    x1: float

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(frozen=True)
class PdfLine:
    """The words that sit on one line of the page, left to right, and how far down it is (``top``, in points)."""

    top: float
    words: tuple[PdfWord, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


#: Words whose tops differ by less than this are on the same line. Rows of a statement are 5 or more points apart.
SAME_LINE_POINTS = 2.5


def lines_from_words(words) -> tuple[PdfLine, ...]:
    """Group ``[(text, x0, x1, top)]`` into lines, top to bottom. For a layout that has no ruled table to read cells from."""
    ordered = sorted(words, key=lambda w: (w[3], w[1]))
    lines: list[list] = []
    for word in ordered:
        if lines and abs(word[3] - lines[-1][0][3]) < SAME_LINE_POINTS:
            lines[-1].append(word)
        else:
            lines.append([word])
    return tuple(
        PdfLine(top=min(w[3] for w in group), words=tuple(PdfWord(w[0], w[1], w[2]) for w in sorted(group, key=lambda w: w[1])))
        for group in lines
    )


@dataclass(frozen=True)
class PdfPage:
    page_number: int
    text: str = ""
    tables: tuple[PdfTable, ...] = ()
    #: Where each word sits, for a statement whose rows are not a ruled table. Empty for a fixture or a source with no positions.
    lines: tuple[PdfLine, ...] = ()

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "tables": [[list(row) for row in table] for table in self.tables],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> PdfPage:
        return cls(
            page_number=raw["page_number"],
            text=raw.get("text", ""),
            tables=tuple(normalise_table(t) for t in raw.get("tables", ())),
        )


@dataclass(frozen=True)
class PdfDocument:
    engine: str
    page_count: int
    pages: tuple[PdfPage, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if len(self.pages) != self.page_count:
            raise PdfTruncationError(
                f"{self.engine} returned {len(self.pages)} of {self.page_count} "
                f"pages. Refusing to return a partial document: a statement "
                f"missing its later pages parses cleanly and balances to the "
                f"wrong closing figure."
            )

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    @property
    def has_text_layer(self) -> bool:
        """False for a scan. Check this before trusting an empty parse."""
        return any(page.has_text for page in self.pages)

    def tables(self):
        """Every table on every page, in reading order."""
        for page in self.pages:
            yield from page.tables

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "page_count": self.page_count,
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> PdfDocument:
        """Rebuild a document from serialised form.

        Test fixtures are stored this way. Extraction is a third-party library's
        job and is covered by its own test; the parsers above are the part worth
        testing exhaustively, and they should not need a binary PDF to do it.
        """
        pages = tuple(PdfPage.from_dict(p) for p in raw["pages"])
        return cls(engine=raw["engine"], page_count=raw["page_count"], pages=pages)


class PdfTextAdapter(abc.ABC):
    @abc.abstractmethod
    def extract(self, data: bytes, password: str | None = None) -> PdfDocument:
        """Return the text and table structure of ``data``.

        ``password`` opens a locked PDF. It is used for this call only: it is never stored, logged or put in an error, and
        an adapter is only handed one when the person gave one.

        Raises :class:`PdfExtractionError` if the file cannot be opened. An
        unreadable *text layer* is not an error -- it yields empty pages, and
        the caller decides whether to route to OCR.
        """

    def page_count(self, data: bytes, password: str | None = None) -> int:
        """How many pages ``data`` has, without extracting any of them.

        This default extracts, so a backend that can count more cheaply should
        override it. Callers use it to refuse an oversized document before
        paying for extraction.
        """
        return (self.extract(data, password) if password else self.extract(data)).page_count

    @property
    def name(self) -> str:
        return type(self).__name__
