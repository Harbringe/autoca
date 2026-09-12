"""Tally Prime XML export, from the approved journal.

Exports what was *posted*, never what was suggested. Before the ledger existed
this file derived vouchers from classifications, which meant a statement could
be exported into a client's books without anyone having approved a line of it.
Reading from ``JournalEntry`` closes that off by construction: an entry exists
only because a senior CA created it.

Tally details that matter and are easy to get wrong:

* **Amount signs are inverted from accounting convention.** A negative
  ``<AMOUNT>`` is a debit and a positive one is a credit, paired with an
  ``<ISDEEMEDPOSITIVE>`` flag saying the same thing again. Get it backwards and
  the import succeeds, the totals tie, and every entry faces the wrong way.
* **Dates are ``YYYYMMDD``**, whatever display format the company uses.
* **An unknown ledger name is created, not rejected.** A trailing space or a
  changed capitalisation silently starts a second ledger and splits the year
  across the two. So masters are exported alongside the vouchers, with their
  groups, and before them -- Tally reads the document in order.
* **``REMOTEID`` is what makes a re-import safe.** With a stable id Tally
  updates the existing voucher instead of adding a second copy, and "export
  again after correcting three entries" is the normal case.

Everything is escaped through :mod:`xml.etree`, never string-formatted. A payee
name containing ``&`` is not exotic, and a hand-built XML string breaks on the
first one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from classify.models import LedgerGroup
from core.money import to_rupees
from ledger.models import JournalEntry


@dataclass(frozen=True)
class ExportResult:
    xml: str
    voucher_count: int
    ledger_count: int
    #: Rows classified but not yet approved. Reported rather than exported: an
    #: export that quietly includes work nobody signed off is worse than a short
    #: one, and the requirements document is explicit that nothing is final
    #: until a CA has approved it.
    unapproved: int = 0


def export_entries(entries, *, company_name: str, include_masters: bool = True) -> ExportResult:
    """Render approved journal entries as a Tally import document."""
    entries = list(entries)
    ledgers = {}
    for entry in entries:
        for line in entry.lines.all():
            ledgers[line.ledger_account.name] = line.ledger_account.group

    return ExportResult(
        xml=render(entries, company_name=company_name, ledgers=ledgers if include_masters else {}),
        voucher_count=len(entries),
        ledger_count=len(ledgers) if include_masters else 0,
    )


def export_statement(statement, *, company_name: str, include_masters: bool = True) -> ExportResult:
    """Everything approved off one statement.

    Superseded entries are left out: the correction that replaced them carries
    both the reversal and the corrected position, so exporting the original as
    well would double-count it. The original remains in this system's own
    records, which is where company law requires it to be visible.
    """
    entries = (
        JournalEntry.objects.filter(
            firm_id=statement.firm_id, source_transaction__statement=statement
        )
        .filter(superseded_by_set__isnull=True)
        .select_related("source_transaction")
        .prefetch_related("lines__ledger_account")
        .order_by("entry_date", "entry_no")
    )

    result = export_entries(
        entries, company_name=company_name, include_masters=include_masters
    )
    return ExportResult(
        xml=result.xml,
        voucher_count=result.voucher_count,
        ledger_count=result.ledger_count,
        unapproved=_unapproved_count(statement),
    )


def render(entries, *, company_name: str, ledgers: dict[str, str] | None = None) -> str:
    """Build the ENVELOPE document for ``entries`` and their ledger masters."""
    envelope = ET.Element("ENVELOPE")

    header = ET.SubElement(envelope, "HEADER")
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"

    body = ET.SubElement(envelope, "BODY")
    import_data = ET.SubElement(body, "IMPORTDATA")

    request_desc = ET.SubElement(import_data, "REQUESTDESC")
    ET.SubElement(request_desc, "REPORTNAME").text = "All Masters" if ledgers else "Vouchers"
    static = ET.SubElement(request_desc, "STATICVARIABLES")
    ET.SubElement(static, "SVCURRENTCOMPANY").text = company_name

    request_data = ET.SubElement(import_data, "REQUESTDATA")

    # Masters first. Tally processes the document in order, so a voucher naming
    # a ledger defined later in the same file would create it under a default
    # group before reaching its real definition.
    for name, group in sorted((ledgers or {}).items()):
        _append_ledger_master(request_data, name, group)

    for entry in entries:
        _append_voucher(request_data, entry)

    return _pretty(envelope)


def ledger_master_group(group: str) -> str:
    """The Tally group name for a :class:`~classify.models.LedgerGroup` value."""
    return dict(LedgerGroup.choices).get(group, "Suspense A/c")


def remote_id_for(entry: JournalEntry) -> str:
    """Stable across re-exports, so Tally updates rather than duplicating.

    Built from the entry's own id rather than the source transaction's, because
    a correction is a different voucher from the entry it replaces and must not
    overwrite it in Tally.
    """
    return f"autoca-{entry.pk}"


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _append_ledger_master(parent, name: str, group: str) -> None:
    message = ET.SubElement(parent, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
    ledger = ET.SubElement(
        message, "LEDGER", {"NAME": name, "ACTION": "Create", "RESERVEDNAME": ""}
    )
    ET.SubElement(ledger, "NAME").text = name
    ET.SubElement(ledger, "PARENT").text = ledger_master_group(group)
    # Tally reuses an existing ledger of the same name rather than erroring, so
    # re-exporting is safe and this doubles as "create if absent".
    ET.SubElement(ledger, "ISDEEMEDPOSITIVE").text = "No"


def _append_voucher(parent, entry: JournalEntry) -> None:
    message = ET.SubElement(parent, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
    node = ET.SubElement(
        message,
        "VOUCHER",
        {
            "REMOTEID": remote_id_for(entry),
            "VCHTYPE": entry.voucher_type,
            "ACTION": "Create",
            "OBJVIEW": "Accounting Voucher View",
        },
    )

    date = entry.entry_date.strftime("%Y%m%d")
    ET.SubElement(node, "DATE").text = date
    ET.SubElement(node, "EFFECTIVEDATE").text = date
    ET.SubElement(node, "VOUCHERTYPENAME").text = entry.voucher_type
    ET.SubElement(node, "VOUCHERNUMBER").text = str(entry.entry_no)
    ET.SubElement(node, "NARRATION").text = entry.narration

    lines = list(entry.lines.all())
    party = next((line for line in lines if line.is_debit), lines[0] if lines else None)
    if party is not None:
        ET.SubElement(node, "PARTYLEDGERNAME").text = party.ledger_account.name

    source = entry.source_transaction
    if source is not None and source.cheque_number:
        ET.SubElement(node, "REFERENCE").text = source.cheque_number
    ET.SubElement(node, "PERSISTEDVIEW").text = "Accounting Voucher View"

    for line in lines:
        item = ET.SubElement(node, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(item, "LEDGERNAME").text = line.ledger_account.name
        # Tally's inversion: the debit side is "deemed positive" and carries a
        # negative amount. See the module docstring.
        ET.SubElement(item, "ISDEEMEDPOSITIVE").text = "Yes" if line.is_debit else "No"
        ET.SubElement(item, "AMOUNT").text = _amount(-line.signed_paise)


def _amount(paise: int) -> str:
    """Rupees with two decimals: Tally's wire format, and the only place the
    ledger leaves paise. Exact, because the divide is Decimal, not float."""
    return f"{to_rupees(paise):.2f}"


def _unapproved_count(statement) -> int:
    from classify.engine import review_queue

    return review_queue(statement.bank_account.client).filter(
        transaction__statement=statement
    ).count()


def _pretty(element) -> str:
    """Indented XML. Tally does not care; the person diffing two exports does."""
    ET.indent(element, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(element, encoding="unicode")
