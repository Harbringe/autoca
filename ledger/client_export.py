"""Everything the system holds for one client, as an Excel workbook.

One sheet per kind of record, every financial year in it, so a firm can take a client's books out whole: the ledgers and their balances,
the bank accounts and every statement row, every voucher and each line of it, the invoices and what settled them, the parties, GST
registrations and returns data, assets, stock, TDS and the rows still waiting for a ledger.

Read-only: it changes nothing. The workbook is written in streaming mode, so a client with tens of thousands of rows does not have to fit in
memory. Amounts are in rupees; dates are real dates. Text typed by other people is neutralised against spreadsheet formulas by the same helper
the GST working paper uses. Account numbers are shown as their last four digits only.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from gst.report import _safe_cell


def _rupees(paise) -> Decimal | None:
    return None if paise is None else Decimal(int(paise)) / 100


def _fy_label(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def _cell(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date | Decimal | int | float | bool) or value is None:
        return value
    return _safe_cell(str(value))


def _sheets(client) -> Iterable[tuple[str, list[str], Iterable[list]]]:
    """``(sheet name, headings, rows)`` for each sheet, in the order they appear."""
    from banking.models import BankAccount, Statement, StatementTransaction
    from classify.models import LedgerAccount, Party, TransactionClassification
    from gst.models import GstRegistration, ReconRun, RegisterInvoice
    from ledger import reports
    from ledger.models import (
        Bill,
        BillAllocation,
        FixedAsset,
        JournalEntry,
        JournalLine,
        LedgerOpening,
        StockEntry,
        StockItem,
        TdsChallan,
    )

    scope = {"firm_id": client.firm_id, "client": client}
    ledgers = {ln.pk: ln for ln in LedgerAccount.objects.filter(**scope)}
    entry_years = sorted(set(JournalEntry.objects.filter(**scope).values_list("financial_year", flat=True)))
    openings = {(o.ledger_id, o.financial_year): o.signed_paise for o in LedgerOpening.objects.filter(**scope)}

    # ---- Ledgers ------------------------------------------------------------------------------------------------------------------
    yield (
        "Ledgers",
        ["Ledger", "Group", "Tally group path", "Tally name", "Alias", "Status", "Active", "Opening balance (Dr+/Cr-)", "Opening as at FY"],
        (
            [
                ln.name,
                ln.get_group_display(),
                ln.tally_group_path,
                ln.tally_name,
                ln.alias,
                ln.status,
                "Yes" if ln.is_active else "No",
                _rupees(openings.get((ln.pk, year))),
                _fy_label(year) if year else "",
            ]
            for ln in sorted(ledgers.values(), key=lambda x: x.name.lower())
            for year in (sorted(y for (lid, y) in openings if lid == ln.pk) or [None])
        ),
    )

    # ---- Trial balance, each year ---------------------------------------------------------------------------------------------------
    def trial_rows():
        for year in entry_years:
            tb = reports.trial_balance(client, year)
            for r in tb.rows:
                yield [
                    _fy_label(year),
                    r.name,
                    str(r.group),
                    _rupees(r.opening_paise),
                    _rupees(r.debit_paise),
                    _rupees(r.credit_paise),
                    _rupees(r.closing_debit_paise),
                    _rupees(r.closing_credit_paise),
                ]

    yield (
        "Trial balance",
        ["Financial year", "Ledger", "Group", "Opening (Dr+/Cr-)", "Debit", "Credit", "Closing debit", "Closing credit"],
        trial_rows(),
    )

    # ---- Bank accounts ------------------------------------------------------------------------------------------------------------
    accounts = {a.pk: a for a in BankAccount.objects.filter(**scope)}
    yield (
        "Bank accounts",
        ["Ledger", "Kind", "Bank code", "Account (last 4)", "IFSC", "Opening balance", "Opening as of", "Active"],
        (
            [a.ledger_name, a.kind, a.bank_code, a.account_last4, a.ifsc, _rupees(a.opening_balance_paise), a.opening_as_of, "Yes" if a.is_active else "No"]
            for a in accounts.values()
        ),
    )
    statements = Statement.objects.filter(bank_account__client=client, firm_id=client.firm_id).select_related("document").order_by("period_start")
    yield (
        "Bank statements",
        ["Account", "File", "Period start", "Period end", "Opening", "Closing", "Total debit", "Total credit", "Rows", "Read by"],
        (
            [
                accounts[s.bank_account_id].ledger_name if s.bank_account_id in accounts else "",
                s.document.original_filename,
                s.period_start,
                s.period_end,
                _rupees(s.opening_balance_paise),
                _rupees(s.closing_balance_paise),
                _rupees(s.total_debit_paise),
                _rupees(s.total_credit_paise),
                s.transaction_count,
                s.parser,
            ]
            for s in statements.iterator(chunk_size=500)
        ),
    )
    classified = {
        c.transaction_id: c
        for c in TransactionClassification.objects.filter(firm_id=client.firm_id, transaction__bank_account__client=client).select_related("party")
    }
    posted = set(
        JournalEntry.objects.filter(**scope, source_transaction__isnull=False).values_list("source_transaction_id", flat=True)
    )

    def bank_rows():
        qs = StatementTransaction.objects.filter(firm_id=client.firm_id, bank_account__client=client).order_by("bank_account_id", "value_date", "row_number")
        for t in qs.iterator(chunk_size=1000):
            c = classified.get(t.pk)
            yield [
                accounts[t.bank_account_id].ledger_name if t.bank_account_id in accounts else "",
                t.value_date,
                t.narration,
                t.cheque_number,
                _rupees(t.debit_paise) if t.debit_paise else None,
                _rupees(t.credit_paise) if t.credit_paise else None,
                _rupees(t.balance_paise),
                ledgers[c.ledger_id].name if c and c.ledger_id in ledgers else "",
                c.party.canonical_name if c and c.party_id else "",
                c.get_method_display() if c else "",
                round(c.confidence * 100) if c and c.confidence else None,
                "Posted" if t.pk in posted else ("Needs a ledger" if not c or not c.ledger_id else "Placed, not posted"),
            ]

    yield (
        "Bank transactions",
        ["Account", "Date", "Narration", "Cheque no.", "Withdrawal", "Deposit", "Balance", "Ledger", "Party", "Placed by", "Confidence %", "State"],
        bank_rows(),
    )

    # ---- Vouchers -------------------------------------------------------------------------------------------------------------------
    entries = JournalEntry.objects.filter(**scope).order_by("entry_date", "voucher_type", "entry_no")
    superseded = set(JournalEntry.objects.filter(**scope, supersedes__isnull=False).values_list("supersedes_id", flat=True))
    yield (
        "Vouchers",
        ["Financial year", "Voucher type", "Voucher no.", "Date", "Kind", "Narration", "Amount", "Marker", "From bank row", "Corrected by a later entry"],
        (
            [
                _fy_label(e.financial_year),
                e.get_voucher_type_display(),
                e.entry_no,
                e.entry_date,
                e.entry_kind,
                e.narration,
                _rupees(sum(ln.amount_paise for ln in e.lines.all() if ln.direction == "DR")),
                e.marker,
                "Yes" if e.source_transaction_id else "No",
                "Yes" if e.pk in superseded else "No",
            ]
            for e in entries.prefetch_related("lines").iterator(chunk_size=500)
        ),
    )
    parties_by_id = {p.pk: p for p in Party.objects.filter(**scope)}

    def line_rows():
        qs = JournalLine.objects.filter(firm_id=client.firm_id, entry__client=client).select_related("entry").order_by("entry__entry_date", "entry__voucher_type", "entry__entry_no", "-signed_paise")
        for ln in qs.iterator(chunk_size=1000):
            e = ln.entry
            party = parties_by_id.get(ln.party_id)
            yield [
                _fy_label(e.financial_year),
                e.get_voucher_type_display(),
                e.entry_no,
                e.entry_date,
                ledgers[ln.ledger_account_id].name if ln.ledger_account_id in ledgers else "",
                party.canonical_name if party else "",
                _rupees(ln.amount_paise) if ln.direction == "DR" else None,
                _rupees(ln.amount_paise) if ln.direction == "CR" else None,
                "Yes" if ln.rcm else "",
                ln.tds_section,
                e.narration,
            ]

    yield (
        "Voucher lines",
        ["Financial year", "Voucher type", "Voucher no.", "Date", "Ledger", "Party", "Debit", "Credit", "RCM", "TDS section", "Narration"],
        line_rows(),
    )

    # ---- Invoices -------------------------------------------------------------------------------------------------------------------
    bills = Bill.objects.filter(**scope).select_related("entry", "document").order_by("bill_date", "reference")
    yield (
        "Invoices",
        [
            "Financial year", "Kind", "Party", "Invoice no.", "Invoice date", "Due date", "Booked on", "Voucher type", "Voucher no.",
            "Taxable", "CGST", "SGST", "IGST", "Cess", "Round off", "TDS", "Reverse charge", "Total", "Document",
        ],
        (
            [
                _fy_label(b.financial_year),
                b.get_kind_display(),
                parties_by_id[b.party_id].canonical_name if b.party_id in parties_by_id else "",
                b.reference,
                b.bill_date,
                b.due_date,
                b.booked_on,
                b.entry.get_voucher_type_display() if b.entry else "",
                b.entry.entry_no if b.entry else None,
                _rupees(b.taxable_paise),
                _rupees(b.cgst_paise),
                _rupees(b.sgst_paise),
                _rupees(b.igst_paise),
                _rupees(b.cess_paise),
                _rupees(b.round_off_paise),
                _rupees(b.tds_paise),
                "Yes" if b.rcm else "",
                _rupees(b.total_paise),
                b.document.original_filename if b.document_id else "",
            ]
            for b in bills.iterator(chunk_size=500)
        ),
    )
    bill_info = {b.pk: b for b in Bill.objects.filter(**scope)}
    allocations = BillAllocation.objects.filter(**scope).select_related("line__entry").order_by("line__entry__entry_date")
    yield (
        "Bill settlements",
        ["Voucher type", "Voucher no.", "Date", "Kind", "Invoice no.", "Party", "Amount"],
        (
            [
                a.line.entry.get_voucher_type_display(),
                a.line.entry.entry_no,
                a.line.entry.entry_date,
                a.kind,
                bill_info[a.bill_id].reference if a.bill_id in bill_info else "",
                parties_by_id[bill_info[a.bill_id].party_id].canonical_name if a.bill_id in bill_info and bill_info[a.bill_id].party_id in parties_by_id else "",
                _rupees(a.amount_paise),
            ]
            for a in allocations.iterator(chunk_size=500)
        ),
    )

    # ---- Parties --------------------------------------------------------------------------------------------------------------------
    yield (
        "Parties",
        ["Name", "Role", "GSTIN", "Own ledger", "Ledger group", "TDS section", "Reverse charge default", "MSME", "Udyam no.", "Active", "Notes"],
        (
            [
                p.canonical_name,
                p.get_role_display(),
                p.gstin,
                ledgers[p.ledger_id].name if p.ledger_id in ledgers else "",
                ledgers[p.ledger_id].get_group_display() if p.ledger_id in ledgers else "",
                p.tds_section,
                "Yes" if p.rcm_default else "",
                "Yes" if p.msme else "",
                p.udyam_no,
                "Yes" if p.is_active else "No",
                p.notes,
            ]
            for p in sorted(parties_by_id.values(), key=lambda x: x.canonical_name.lower())
        ),
    )

    # ---- GST ------------------------------------------------------------------------------------------------------------------------
    yield (
        "GST registrations",
        ["GSTIN", "State code", "Type", "Active"],
        ([r.gstin, r.state_code, r.registration_type, "Yes" if r.is_active else "No"] for r in GstRegistration.objects.filter(**scope)),
    )
    runs = {r.pk: r for r in ReconRun.objects.filter(firm_id=client.firm_id, client=client)}
    yield (
        "GST register rows",
        ["Supplier", "GSTIN", "Invoice no.", "Invoice date", "Section", "HSN", "Taxable", "CGST", "SGST", "IGST", "Cess", "ITC available", "RCM", "Blocked", "Category"],
        (
            [
                r.supplier_name, r.gstin, r.invoice_no, r.invoice_date, r.section, r.hsn,
                _rupees(r.taxable_paise), _rupees(r.cgst_paise), _rupees(r.sgst_paise), _rupees(r.igst_paise), _rupees(r.cess_paise),
                "Yes" if r.itc_available else "No", "Yes" if r.rcm else "", "Yes" if r.blocked else "", r.category,
            ]
            for r in RegisterInvoice.objects.filter(firm_id=client.firm_id, run_id__in=list(runs)).iterator(chunk_size=500)
        ),
    )

    # ---- Fixed assets, stock, TDS, openings ------------------------------------------------------------------------------------------
    yield (
        "Fixed assets",
        ["Asset", "Ledger", "Cost", "Residual value", "Put to use", "Method", "Life (years)", "Rate %", "Disposed on", "Sale value"],
        (
            [
                a.name, ledgers[a.ledger_id].name if a.ledger_id in ledgers else "", _rupees(a.cost_paise), _rupees(a.residual_paise), a.put_to_use,
                a.method, a.life_years, a.rate_bp / 100, a.disposed_on, _rupees(a.disposal_paise),
            ]
            for a in FixedAsset.objects.filter(**scope)
        ),
    )
    yield (
        "Stock items",
        ["Item", "Unit", "HSN/SAC"],
        ([s.name, s.unit, s.hsn_sac] for s in StockItem.objects.filter(**scope)),
    )
    yield (
        "Stock movements",
        ["Date", "Kind", "Direction", "Item", "Unit", "Quantity", "Value", "Note"],
        (
            [s.entry_date, s.kind, s.direction, s.name, s.unit, s.quantity, _rupees(s.value_paise), s.note]
            for s in StockEntry.objects.filter(**scope).order_by("entry_date")
        ),
    )
    yield (
        "TDS challans",
        ["Section", "BSR code", "Serial", "Paid on", "Voucher no.", "Amount"],
        (
            [c.section, c.bsr_code, c.serial, c.paid_on, c.entry.entry_no, _rupees(c.entry.total_paise)]
            for c in TdsChallan.objects.filter(**scope).select_related("entry")
        ),
    )

    # ---- Waiting for a ledger -------------------------------------------------------------------------------------------------------
    def waiting_rows():
        qs = TransactionClassification.objects.filter(firm_id=client.firm_id, transaction__bank_account__client=client).exclude(transaction_id__in=posted).select_related("transaction", "party")
        for c in qs.iterator(chunk_size=1000):
            t = c.transaction
            yield [
                t.value_date,
                t.narration,
                _rupees(t.debit_paise) if t.debit_paise else None,
                _rupees(t.credit_paise) if t.credit_paise else None,
                ledgers[c.ledger_id].name if c.ledger_id in ledgers else c.suggested_ledger_name,
                c.party.canonical_name if c.party_id else "",
                c.get_method_display(),
                round(c.confidence * 100) if c.confidence else None,
                c.rationale,
            ]

    yield (
        "Not yet posted",
        ["Date", "Narration", "Withdrawal", "Deposit", "Suggested ledger", "Party", "Placed by", "Confidence %", "Why"],
        waiting_rows(),
    )


def workbook(client) -> bytes:
    """The client's whole books as an .xlsx. The first sheet says what is in the others."""
    from openpyxl import Workbook

    book = Workbook(write_only=True)
    summary = book.create_sheet("Summary")
    counts: list[tuple[str, int]] = []
    pending = []
    for name, headings, rows in _sheets(client):
        sheet = book.create_sheet(name[:31])
        sheet.freeze_panes = "A2"
        sheet.append([_safe_cell(h) for h in headings])
        n = 0
        for row in rows:
            sheet.append([_cell(v) for v in row])
            n += 1
        counts.append((name, n))
        pending.append(name)
    summary.append(["Client", _safe_cell(client.name)])
    summary.append(["Financial year starts", client.fy_start])
    summary.append(["Exported", datetime.now().replace(microsecond=0)])
    summary.append([])
    summary.append(["Sheet", "Rows"])
    for name, n in counts:
        summary.append([name, n])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
