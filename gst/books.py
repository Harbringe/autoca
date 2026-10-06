"""The purchase register, taken from the books instead of from a file.

A register uploaded as a spreadsheet is a second copy of what the books already say, typed or exported separately, and the
two can quietly disagree. When the invoices are booked as bills, the register for a return month *is* those bills: this
builds the run's register rows from them, so what is matched against GSTR-2B is exactly what the books hold, and a bill
missing from the register cannot happen.

Which bills belong to which return: a bill carries a blind index of the client's own GSTIN it was booked under
(``Bill.own_gstin_hash``), so it lands in the right return without the books importing anything from here. A bill booked
with no GSTIN belongs to the client's only registration when it has just one; with several, it is left out and counted, so
the person can see what was not assigned rather than have it guessed.

This module reads ``ledger`` but nothing outside ``gst/`` imports it, so the add-on stays removable.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from gst.matching import Section
from gst.models import GstRegistration, ReconRun, RegisterInvoice
from gst.services import _require_open
from ledger.models import Bill, BillKind


@dataclass(frozen=True)
class BooksLoad:
    rows: int
    #: Bills in the month with no GSTIN of the client's, left out because the client has several registrations.
    unassigned: int


def _month_end(start: datetime.date) -> datetime.date:
    return (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


@transaction.atomic
def load_register_from_books(run: ReconRun) -> BooksLoad:
    """Replace the run's register rows with the month's purchase bills and the debit notes that reverse purchases."""
    _require_open(run)
    only_registration = GstRegistration.objects.filter(client=run.client).count() == 1
    month = Q(bill_date__gte=run.period_start, bill_date__lt=_month_end(run.period_start))
    kinds = Q(kind__in=[BillKind.PURCHASE, BillKind.DEBIT_NOTE])
    base = Bill.objects.filter(firm_id=run.firm_id, client=run.client).filter(month, kinds).select_related("party")

    mine = Q(own_gstin_hash=run.registration.gstin_hash)
    if only_registration:
        mine |= Q(own_gstin_hash="")
    bills = list(base.filter(mine).order_by("bill_date", "created_at"))
    unassigned = 0 if only_registration else base.filter(own_gstin_hash="").count()

    run.register_rows.all().delete()
    rows = []
    for position, bill in enumerate(bills, start=1):
        row = RegisterInvoice(
            firm_id=run.firm_id,
            run=run,
            invoice_no=bill.reference[:64],
            invoice_date=bill.bill_date,
            supplier_name=bill.party.canonical_name[:255],
            # A debit note the client raises on a supplier is that supplier's credit note: it reduces the credit claimed.
            section=(Section.CDN if bill.kind == BillKind.DEBIT_NOTE else Section.B2B).value,
            taxable_paise=bill.taxable_paise,
            igst_paise=bill.igst_paise,
            cgst_paise=bill.cgst_paise,
            sgst_paise=bill.sgst_paise,
            cess_paise=bill.cess_paise,
            source_row=position,
            rcm=bill.rcm,
        )
        row.set_gstin(bill.party.gstin)
        rows.append(row)
    RegisterInvoice.objects.bulk_create(rows)
    # The books are the source, so there is no uploaded file to point at: the run records that its register is the books.
    run.register_document = None
    run.register_from_books = True
    run.save(update_fields=["register_document", "register_from_books"])
    return BooksLoad(rows=len(rows), unassigned=unassigned)
