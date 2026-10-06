"""What the reader sees in a statement, so a person can correct one wrong guess.

When a statement is refused the usual cause is one column read as the wrong thing. This shows the first rows of the table
the reader found, which column it thinks is which (if it got that far), and why it stopped, so the person can name the
columns and upload again. The columns they name are still proved against the statement's own balances.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from banking.parsers import detect_parser
from banking.parsers.columns import ColumnInferenceError, infer_columns
from banking.parsers.generic import GenericStatementParser
from integrations.pdf.base import PdfDocument

PREVIEW_ROWS = 12
CELL = 48


@dataclass
class LayoutPreview:
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    width: int = 0
    total_rows: int = 0
    #: Role -> column index, when the reader got as far as proving a layout.
    proposed: dict[str, int] = field(default_factory=dict)
    error: str = ""


def preview(document: PdfDocument) -> LayoutPreview:
    reader = GenericStatementParser()
    header, rows, _ = reader._collect(document)
    out = LayoutPreview(total_rows=len(rows))
    if not rows:
        out.error = "No table of transactions was found on any page."
        return out
    out.width = max(len(r) for r in rows)
    clip = lambda r: [(" ".join((c or "").split()))[:CELL] for c in r] + [""] * (out.width - len(r))  # noqa: E731
    out.header = clip(header) if header else []
    out.rows = [clip(r) for r in rows[:PREVIEW_ROWS]]
    try:
        liability = bool(getattr(detect_parser(document), "liability", False))
        mapping = infer_columns(header, rows, liability=liability)
    except ColumnInferenceError as exc:
        out.error = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001 -- a preview must never be the thing that fails
        out.error = str(exc)
        return out
    out.proposed = {
        role: getattr(mapping, role)
        for role in GenericStatementParser.LAYOUT_ROLES
        if getattr(mapping, role, None) is not None and getattr(mapping, role) >= 0
    }
    return out
