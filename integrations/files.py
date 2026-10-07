"""Any file a client sends, as the one document shape the readers already know.

Bank statements and invoices arrive as PDFs, but also as Excel sheets, CSVs, Word files and photos or scans of paper. This
module sniffs what a file *really* is (from its bytes, never its name or declared type) and turns it into a
:class:`~integrations.pdf.base.PdfDocument`, so every reader above it works unchanged:

* a PDF goes through the configured PDF adapter, as before;
* an Excel sheet, a CSV or a Word file is born-digital text: each sheet or table becomes a table of cells, which is exactly
  what a ruled bank-statement PDF yields, so the statement reader and its balance proof apply as they are;
* a photo or scan has no text. It becomes pages with none, plus the page images, and is read by the vision model, which
  copies and never decides, and whose reading is proved the same way (see ``banking/scan.py`` and ``ledger/invoice_vision``).

Nothing here trusts the file. Spreadsheets and Word files are zip archives, so their declared uncompressed size is checked
before anything is opened; XML is parsed with ``defusedxml``; images have a pixel ceiling; rows and pages are capped.
"""

from __future__ import annotations

import csv
import datetime
import io
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from integrations.pdf.base import PdfDocument, PdfExtractionError, PdfPage, normalise_table

#: What a person may send. The words are for messages.
ACCEPTED = "PDF, Excel (.xlsx), CSV, Word (.docx), or an image (JPG, PNG, WEBP, TIFF)"

MAX_UNCOMPRESSED_BYTES = 120 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 60
MAX_SHEETS = 40
MAX_IMAGE_PIXELS = 60_000_000
MAX_IMAGE_SIDE = 2200
MAX_IMAGE_PAGES = 40

PDF, XLSX, DOCX, CSV, IMAGE = "pdf", "xlsx", "docx", "csv", "image"
_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "TIFF", "BMP"}


class UnsupportedFileError(PdfExtractionError):
    """The file is not one of the kinds that can be read. The message says what to send instead."""


@dataclass(frozen=True)
class LoadedFile:
    kind: str
    document: PdfDocument
    #: One PNG per page, for a photo or scan; ``None`` otherwise (a PDF is drawn later, only if it turns out to be a scan).
    images: list[bytes] | None
    extension: str
    content_type: str

    @property
    def is_image(self) -> bool:
        return self.kind == IMAGE


_TYPES = {
    PDF: ("pdf", "application/pdf"),
    XLSX: ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    DOCX: ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    CSV: ("csv", "text/csv"),
    IMAGE: ("png", "image/png"),
}


def sniff(data: bytes, filename: str = "") -> str | None:
    """What the file is, from its bytes. ``None`` when it is none of the readable kinds.

    The name is used only to tell a CSV from other text, because a CSV has no signature of its own.
    """
    head = data[:16]
    if head.startswith(b"%PDF"):
        return PDF
    if head.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return DOCX
        if "xl/workbook.xml" in names:
            return XLSX
        return None
    if _is_image(head):
        return IMAGE
    if filename.lower().endswith((".csv", ".txt")) and _looks_like_text(data):
        return CSV
    return None


def _is_image(head: bytes) -> bool:
    return (
        head.startswith(b"\xff\xd8\xff")  # JPEG
        or head.startswith(b"\x89PNG\r\n\x1a\n")
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
        or head.startswith((b"GIF87a", b"GIF89a"))
        or head.startswith((b"II*\x00", b"MM\x00*"))  # TIFF
        or head.startswith(b"BM")
    )


def _looks_like_text(data: bytes) -> bool:
    sample = data[:4096]
    return b"\x00" not in sample


def describe_refusal(data: bytes, filename: str = "") -> str:
    """Why a file that sniffed as nothing cannot be read, in words that say what to do."""
    lower = filename.lower()
    if lower.endswith(".xls") or data.startswith(b"\xd0\xcf\x11\xe0"):
        return "This is an old-format Office file (.xls or .doc). Open it and save it as .xlsx (Excel) or .docx (Word), or as PDF, then upload that."
    if lower.endswith((".heic", ".heif")):
        return "HEIC photos cannot be read. Export the photo as JPG or PNG, or print it to PDF, then upload that."
    return f"This file type cannot be read. Send a {ACCEPTED}."


def load(data: bytes, filename: str = "") -> LoadedFile:
    """Read ``data`` into a :class:`LoadedFile`, or raise :class:`UnsupportedFileError` / ``PdfExtractionError``."""
    kind = sniff(data, filename)
    if kind is None:
        raise UnsupportedFileError(describe_refusal(data, filename))
    extension, content_type = _TYPES[kind]
    if kind == PDF:
        from integrations.registry import get_pdf

        return LoadedFile(PDF, get_pdf().extract(data), None, extension, content_type)
    if kind == XLSX:
        return LoadedFile(XLSX, _read_xlsx(data), None, extension, content_type)
    if kind == DOCX:
        return LoadedFile(DOCX, _read_docx(data), None, extension, content_type)
    if kind == CSV:
        return LoadedFile(CSV, _read_csv(data), None, extension, content_type)
    images = _read_images(data)
    pages = tuple(PdfPage(page_number=i + 1) for i in range(len(images)))
    return LoadedFile(IMAGE, PdfDocument(engine="image", page_count=len(pages), pages=pages), images, extension, content_type)


# ---------------------------------------------------------------------------
# Zip archives: check the size they claim before opening anything
# ---------------------------------------------------------------------------


def _guard_zip(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PdfExtractionError("This file is damaged and could not be opened.") from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
        raise PdfExtractionError("This file is far larger than it looks once opened, so it was refused.")
    return archive


# ---------------------------------------------------------------------------
# Cells as the strings a statement reader expects
# ---------------------------------------------------------------------------


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%d-%m-%Y") if value.time() == datetime.time(0) else value.strftime("%d-%m-%Y %H:%M")
    if isinstance(value, datetime.date):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        try:
            number = Decimal(repr(value))
        except InvalidOperation:
            return str(value)
        shown = format(number, "f")
        if "." in shown and len(shown.split(".")[1]) <= 2:
            return f"{number:.2f}"
        return shown
    return " ".join(str(value).split())


def _page_of(number: int, rows: list[list[str]]) -> PdfPage:
    rows = [row for row in rows if any(cell for cell in row)]
    text = "\n".join("  ".join(cell for cell in row if cell) for row in rows)
    return PdfPage(page_number=number, text=text, tables=(normalise_table(rows),) if rows else ())


def _document(engine: str, pages: list[PdfPage]) -> PdfDocument:
    if not pages:
        pages = [PdfPage(page_number=1)]
    return PdfDocument(engine=engine, page_count=len(pages), pages=tuple(pages))


# ---------------------------------------------------------------------------
# Excel, CSV
# ---------------------------------------------------------------------------


def _read_xlsx(data: bytes) -> PdfDocument:
    _guard_zip(data)
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for a bad workbook
        raise PdfExtractionError("This Excel file could not be opened.") from exc
    pages: list[PdfPage] = []
    try:
        for sheet in book.worksheets[:MAX_SHEETS]:
            rows: list[list[str]] = []
            for index, raw in enumerate(sheet.iter_rows(values_only=True)):
                if index >= MAX_ROWS:
                    raise PdfExtractionError(f"A sheet has more than {MAX_ROWS:,} rows. Send one statement at a time.")
                row = [_cell(v) for v in raw[:MAX_COLUMNS]]
                while row and not row[-1]:
                    row.pop()
                rows.append(row)
            page = _page_of(len(pages) + 1, rows)
            if page.has_text:
                pages.append(page)
    finally:
        book.close()
    return _document("xlsx", pages)


def _read_csv(data: bytes) -> PdfDocument:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise PdfExtractionError("This CSV could not be read as text.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows: list[list[str]] = []
    for index, raw in enumerate(csv.reader(io.StringIO(text), dialect)):
        if index >= MAX_ROWS:
            raise PdfExtractionError(f"This CSV has more than {MAX_ROWS:,} rows. Send one statement at a time.")
        rows.append([" ".join(c.split()) for c in raw[:MAX_COLUMNS]])
    return _document("csv", [_page_of(1, rows)])


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(data: bytes) -> PdfDocument:
    archive = _guard_zip(data)
    from defusedxml import ElementTree

    try:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    except Exception as exc:
        raise PdfExtractionError("This Word file could not be opened.") from exc
    body = root.find(f"{_W}body")
    if body is None:
        raise PdfExtractionError("This Word file has no content.")

    def paragraph(node) -> str:
        return " ".join("".join(t.text or "" for t in node.iter(f"{_W}t")).split())

    lines: list[str] = []
    tables = []
    for child in body:
        if child.tag == f"{_W}p":
            text = paragraph(child)
            if text:
                lines.append(text)
        elif child.tag == f"{_W}tbl":
            rows = []
            for tr in child.iter(f"{_W}tr"):
                row = [" ".join(paragraph(p) for p in tc.iter(f"{_W}p")).strip() for tc in tr.findall(f"{_W}tc")][:MAX_COLUMNS]
                rows.append(row)
                if any(row):
                    lines.append("  ".join(c for c in row if c))
            rows = [r for r in rows if any(r)]
            if rows:
                tables.append(normalise_table(rows))
            if len(rows) > MAX_ROWS:
                raise PdfExtractionError(f"A table has more than {MAX_ROWS:,} rows.")
    page = PdfPage(page_number=1, text="\n".join(lines), tables=tuple(tables))
    return _document("docx", [page] if page.has_text else [])


# ---------------------------------------------------------------------------
# Photos and scans
# ---------------------------------------------------------------------------


def _read_images(data: bytes) -> list[bytes]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in _IMAGE_FORMATS:
            raise UnsupportedFileError(describe_refusal(b"", ""))
        frames = getattr(image, "n_frames", 1)
        if frames > MAX_IMAGE_PAGES:
            raise PdfExtractionError(f"This image has {frames} pages; send up to {MAX_IMAGE_PAGES}.")
        pages: list[bytes] = []
        for index in range(frames):
            image.seek(index)
            frame = ImageOps.exif_transpose(image).convert("RGB")
            if max(frame.size) > MAX_IMAGE_SIDE:
                frame.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            out = io.BytesIO()
            frame.save(out, format="PNG", optimize=True)
            pages.append(out.getvalue())
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise PdfExtractionError("This image could not be opened, or is too large.") from exc
    return pages
