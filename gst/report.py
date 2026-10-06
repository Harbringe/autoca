"""The reconciliation as data, and as the Excel working paper.

One function builds the report; the API returns it as JSON and the export lays
the same dictionary out in a workbook, so the screen and the paper a CA files
can never disagree about a number.
"""

from __future__ import annotations

import io

from gst import services
from gst.matching import TAX_HEADS, ItcStatus, MatchKind, Section
from gst.models import DecisionKind, ReconRun

#: The order groups appear in: the things a person must act on first.
GROUP_ORDER = [
    MatchKind.AMOUNT_MISMATCH,
    MatchKind.TAX_HEAD_MISMATCH,
    MatchKind.WRONG_PERIOD,
    MatchKind.POSSIBLE_MATCH,
    MatchKind.MISSING_IN_2B,
    MatchKind.MISSING_IN_BOOKS,
    MatchKind.DUPLICATE,
    MatchKind.INVALID_GSTIN,
    MatchKind.RCM,
    MatchKind.IMPORT,
    MatchKind.ISD_CREDIT,
    MatchKind.MATCHED,
]

GROUP_TITLES = {
    MatchKind.AMOUNT_MISMATCH: "Amount differences",
    MatchKind.TAX_HEAD_MISMATCH: "Tax head differs (IGST vs CGST/SGST)",
    MatchKind.WRONG_PERIOD: "In a different month's GSTR-2B",
    MatchKind.IMPORT: "Imports of goods (bill of entry)",
    MatchKind.ISD_CREDIT: "ISD credit",
    MatchKind.POSSIBLE_MATCH: "Possible matches (invoice number differs)",
    MatchKind.MISSING_IN_2B: "In our books, not in GSTR-2B",
    MatchKind.MISSING_IN_BOOKS: "In GSTR-2B, not in our books",
    MatchKind.DUPLICATE: "Duplicate invoices",
    MatchKind.INVALID_GSTIN: "Invalid GSTIN",
    MatchKind.RCM: "Reverse charge",
    MatchKind.MATCHED: "Matched",
}


def _row(inv) -> dict | None:
    if inv is None:
        return None
    return {
        "gstin": inv.gstin,
        "invoice_no": inv.invoice_no,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "supplier_name": inv.supplier_name,
        "hsn": inv.hsn,
        "section": inv.section,
        "taxable_paise": inv.taxable_paise,
        "igst_paise": inv.igst_paise,
        "cgst_paise": inv.cgst_paise,
        "sgst_paise": inv.sgst_paise,
        "cess_paise": inv.cess_paise,
    }


def run_report(run: ReconRun) -> dict:
    standings = services.standings(run)
    groups = []
    for kind in GROUP_ORDER:
        items = [s for s in standings if s.match.kind == kind.value]
        if not items:
            continue
        groups.append(
            {
                "kind": kind.value,
                "title": GROUP_TITLES[kind],
                "count": len(items),
                "rows": [
                    {
                        "id": str(s.match.pk),
                        "itc_status": s.match.itc_status,
                        "eligible_paise": s.eligible_paise,
                        "ineligible_paise": s.ineligible_paise,
                        "cause": s.match.cause,
                        "action": s.match.action,
                        "timing": s.match.timing,
                        "differences": s.match.differences,
                        "book": _row(s.match.register_invoice),
                        "portal": _row(s.match.portal_invoice),
                        "decision": None
                        if s.decision is None
                        else {
                            "kind": s.decision.kind,
                            "note": s.decision.note,
                            "at": s.decision.created_at.isoformat(),
                        },
                    }
                    for s in items
                ],
            }
        )
    actions = [
        {"match": str(s.match.pk), "text": s.match.action}
        for s in standings
        if s.match.action and s.decision is None and s.match.kind != MatchKind.MATCHED.value
    ]
    return {
        "id": str(run.pk),
        "registration": {
            "id": str(run.registration_id),
            "gstin": run.registration.gstin,
            "state_code": run.registration.state_code,
        },
        "period_start": run.period_start.isoformat(),
        "status": run.status,
        "signed_off_at": run.signed_off_at.isoformat() if run.signed_off_at else None,
        "has_register": run.register_document_id is not None or run.register_from_books,
        "register_from_books": run.register_from_books,
        "has_portal": run.portal_document_id is not None,
        "summary": services.summarise(run),
        "gstr3b": gstr3b_table4(run),
        "groups": groups,
        "actions": actions,
    }


def _heads(kind: str, book, portal) -> dict[str, int]:
    """The credit's tax heads for a row, signed like the row itself.

    Credit follows the portal where the portal is the only or the authoritative
    source (imports, ISD, a head mismatch); otherwise it is the smaller of the
    two per head, as in ``matching._itc_for``.
    """
    row = book or portal
    sign = -1 if row.section == Section.CDN.value else 1
    if kind == MatchKind.RCM.value:
        src = {h: getattr(book, h) for h in TAX_HEADS}
    elif book is None or kind in (
        MatchKind.TAX_HEAD_MISMATCH.value,
        MatchKind.IMPORT.value,
        MatchKind.ISD_CREDIT.value,
    ):
        src = {h: getattr(portal, h) for h in TAX_HEADS}
    else:
        src = {h: min(getattr(book, h), getattr(portal, h)) for h in TAX_HEADS}
    return {h: v * sign for h, v in src.items()}


def gstr3b_table4(run: ReconRun) -> list[dict]:
    """This reconciliation laid out as GSTR-3B Table 4 (eligible ITC).

    Indicative, not the return: it is what this reconciliation supports, per tax
    head, in the rows a CA copies across. Rows nobody has claimed or decided --
    missing from GSTR-2B, wrong period -- appear nowhere, since they are not
    credit yet.
    """
    lines = {
        code: {"code": code, "label": label, **dict.fromkeys(TAX_HEADS, 0)}
        for code, label in [
            ("4A(1)", "Import of goods"),
            ("4A(3)", "Inward supplies liable to reverse charge (claimable after payment)"),
            ("4A(4)", "Inward supplies from ISD"),
            ("4A(5)", "All other ITC"),
            ("4B(1)", "ITC reversed -- section 17(5) and rules 38, 42, 43"),
            ("4D(2)", "Ineligible ITC -- other (not available on GSTR-2B, or disallowed)"),
        ]
    }

    def add(code, heads):
        for h in TAX_HEADS:
            lines[code][h] += heads[h]

    for st in services.standings(run):
        m = st.match
        book, portal = m.register_invoice, m.portal_invoice
        if book is None and portal is None:
            continue
        if portal is None and m.kind != MatchKind.RCM.value:
            continue  # nothing on the portal to claim against: not credit yet
        heads = _heads(m.kind, book, portal)
        disallowed = st.decision is not None and st.decision.kind == DecisionKind.DISALLOW_ITC
        if m.kind == MatchKind.RCM.value:
            add("4A(3)", heads)
        elif st.eligible_paise != 0:
            code = {"import": "4A(1)", "isd_credit": "4A(4)"}.get(m.kind, "4A(5)")
            add(code, heads)
        elif m.itc_status == ItcStatus.BLOCKED.value and st.ineligible_paise != 0:
            add("4B(1)", heads)
        elif st.ineligible_paise != 0 and (
            disallowed or (m.kind in ("matched", "import", "isd_credit"))
        ):
            add("4D(2)", heads)
    return list(lines.values())


def _rupees(paise: int) -> float:
    return paise / 100


def _safe_cell(value):
    """A cell value that Excel will show and never evaluate.

    Supplier names and invoice numbers are typed by other people; a leading
    ``= + - @``, tab or carriage return makes a spreadsheet run them as a
    formula. Characters outside XML 1.0 make the workbook unwritable.
    """
    if not isinstance(value, str):
        return value
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        value = "'" + value
    return value


def working_paper(run: ReconRun) -> bytes:
    """The workbook a CA files behind the return."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    def _append(sheet, row):
        sheet.append([_safe_cell(v) for v in row])

    report = run_report(run)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    bold = Font(bold=True)
    _append(ws, [f"GST reconciliation -- {run.client.name}"])
    ws["A1"].font = Font(bold=True, size=13)
    _append(ws, [f"GSTIN {report['registration']['gstin']}", f"Return period {run.period_start:%B %Y}"])
    _append(ws, ["Status", "Signed off" if run.status == "signed_off" else "DRAFT -- not signed off"])
    _append(ws, [])
    s = report["summary"]
    for label, key in [
        ("Eligible ITC", "eligible_paise"),
        ("Blocked credit", "blocked_paise"),
        ("Ineligible / not yet claimable", "ineligible_paise"),
        ("Reverse-charge tax payable", "rcm_liability_paise"),
        ("In GSTR-2B but not booked", "unclaimed_in_2b_paise"),
    ]:
        _append(ws, [label, _rupees(s[key])])
    _append(ws, [])
    _append(ws, ["Group", "Invoices"])
    for c in ws[ws.max_row]:
        c.font = bold
    for g in report["groups"]:
        _append(ws, [g["title"], g["count"]])
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 22

    t = wb.create_sheet("GSTR-3B Table 4")
    _append(t, ["Indicative -- verify against your ledgers before filing."])
    _append(t, ["Table", "Description", "IGST", "CGST", "SGST", "Cess"])
    for c in t[2]:
        c.font = bold
    for line in report["gstr3b"]:
        _append(t, [line["code"], line["label"]] + [_rupees(line[h]) for h in TAX_HEADS])
    t.column_dimensions["B"].width = 66

    heads = ["Supplier GSTIN", "Supplier", "Invoice no", "Date", "Books taxable", "Books tax",
             "2B taxable", "2B tax", "Eligible ITC", "Cause", "Action", "Decision"]
    for g in report["groups"]:
        sheet = wb.create_sheet(g["title"][:31].replace("/", "-"))
        _append(sheet, heads)
        for c in sheet[1]:
            c.font = bold
        for r in g["rows"]:
            b, p = r["book"], r["portal"]
            ref = b or p

            def tax(x):
                return None if x is None else _rupees(
                    x["igst_paise"] + x["cgst_paise"] + x["sgst_paise"] + x["cess_paise"]
                )

            _append(sheet, [
                ref["gstin"], ref["supplier_name"], ref["invoice_no"], ref["invoice_date"],
                None if b is None else _rupees(b["taxable_paise"]), tax(b),
                None if p is None else _rupees(p["taxable_paise"]), tax(p),
                _rupees(r["eligible_paise"]), r["cause"], r["action"],
                (r["decision"] or {}).get("kind", ""),
            ])
        for col, width in zip("ABCDEFGHIJKL", [18, 26, 16, 12, 14, 12, 14, 12, 14, 50, 50, 14], strict=True):
            sheet.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
