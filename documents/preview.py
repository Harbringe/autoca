"""Showing any stored file as pages, for the viewer beside a form.

Whatever was uploaded, the viewer shows the same thing: page images with next/previous and zoom. A PDF is drawn page by
page, a photo or scan is its own page(s), and an Excel sheet, CSV or Word file is converted to pages: its text and tables set
out on A4 sheets. Nothing is stored; a page is drawn when it is asked for, from the file as kept.

The converted view is a plain rendition of what was read (text and tables), not the original layout, so it is for reading the
figures against the form, not for printing. The original is always one download away.
"""

from __future__ import annotations

import io
import textwrap

from integrations import files

#: A4 at 110 dpi, in pixels.
PAGE_W, PAGE_H = 910, 1286
MARGIN = 54
SCALE = 1.5  # PDF points to pixels, about 108 dpi
#: Bounds on what one request may cost: a page is drawn no bigger than this, and a converted file shows this many pages.
MAX_SIDE_PX = 2000
MAX_CONVERTED_PAGES = 40


class _Enough(Exception):
    """The preview has all the pages it will show."""


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow has one size only
        return ImageFont.load_default()


def _convert(loaded: files.LoadedFile) -> list[bytes]:
    """Set an office document's text and tables out on A4 pages."""
    from PIL import Image, ImageDraw

    body, small = _font(17), _font(15)
    pages: list[Image.Image] = []
    state = {"y": MARGIN}

    def new_page():
        page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        pages.append(page)
        state["y"] = MARGIN
        return ImageDraw.Draw(page)

    draw = new_page()

    def need(height: int):
        nonlocal draw
        if state["y"] + height > PAGE_H - MARGIN:
            if len(pages) >= MAX_CONVERTED_PAGES:
                raise _Enough
            draw = new_page()

    try:
        for document_page in loaded.document.pages:
            for line in document_page.text.splitlines():
                if not line.strip():
                    continue
                for wrapped in textwrap.wrap(line, 78) or [""]:
                    need(26)
                    draw.text((MARGIN, state["y"]), wrapped, fill="#1a1a1a", font=body)
                    state["y"] += 26
            for table in document_page.tables:
                columns = max(len(row) for row in table)
                width = (PAGE_W - 2 * MARGIN) // max(columns, 1)
                state["y"] += 10
                for row in table:
                    need(30)
                    for index, cell in enumerate(row):
                        x = MARGIN + index * width
                        draw.rectangle([x, state["y"], x + width, state["y"] + 28], outline="#c8c8c8")
                        draw.text((x + 6, state["y"] + 6), str(cell)[: max(width // 9, 4)], fill="#1a1a1a", font=small)
                    state["y"] += 28
                state["y"] += 10
    except _Enough:
        pass  # a very long sheet is shown as its first pages; the original has the rest
    out = []
    for page in pages:
        buffer = io.BytesIO()
        page.save(buffer, format="PNG", optimize=True)
        out.append(buffer.getvalue())
    return out


def _pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def _pdf_page(data: bytes, index: int) -> bytes | None:
    """One PDF page as a PNG, never bigger than ``MAX_SIDE_PX`` however large the page claims to be."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        if index >= len(pdf):
            return None
        page = pdf[index]
        try:
            width, height = page.get_size()
            scale = min(SCALE, MAX_SIDE_PX / max(width, height, 1))
            buffer = io.BytesIO()
            page.render(scale=scale).to_pil().convert("RGB").save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
        finally:
            page.close()
    finally:
        pdf.close()


def _converted(data: bytes, filename: str, key: str) -> list[bytes]:
    """The pages of a photo, sheet or Word file, kept for a few minutes so turning pages does not redraw them."""
    from django.core.cache import cache

    cached = cache.get(f"preview:{key}")
    if cached is not None:
        return cached
    loaded = files.load(data, filename)
    pages = list(loaded.images or []) if loaded.is_image else _convert(loaded)
    cache.set(f"preview:{key}", pages, timeout=600)
    return pages


def page_count(data: bytes, filename: str, key: str) -> int:
    """How many pages the viewer will show. Raises ``PdfExtractionError`` for a file that cannot be shown."""
    kind = files.sniff(data, filename)
    if kind is None:
        raise files.UnsupportedFileError(files.describe_refusal(data, filename))
    if kind == files.PDF:
        return _pdf_page_count(data)
    return len(_converted(data, filename, key))


def page_image(data: bytes, filename: str, key: str, number: int) -> bytes | None:
    """Page ``number`` (from 1) as a PNG, or None when there is no such page."""
    kind = files.sniff(data, filename)
    if kind is None:
        raise files.UnsupportedFileError(files.describe_refusal(data, filename))
    if number < 1:
        return None
    if kind == files.PDF:
        return _pdf_page(data, number - 1)
    pages = _converted(data, filename, key)
    return pages[number - 1] if number <= len(pages) else None
