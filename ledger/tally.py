"""Tally Prime XML export.

Tally imports an ``ENVELOPE`` document through its ODBC/HTTP gateway or from a
file. The shape below is what Tally Prime accepts; the details that matter and
are easy to get wrong:

* **Amount signs are inverted from accounting convention.** A negative
  ``<AMOUNT>`` is a debit and a positive one is a credit, paired with an
  ``<ISDEEMEDPOSITIVE>`` flag saying the same thing again. Get it backwards and
  the import succeeds, the totals tie, and every entry faces the wrong way.
* **Dates are ``YYYYMMDD``** with no separators, regardless of the display
  format the company uses.
* **Ledgers are matched by name, and an unknown name is created, not
  rejected.** A trailing space or a changed capitalisation does not fail the
  import; it silently starts a second ledger and splits the year across the two.
  So masters are exported alongside the vouchers, with their groups, rather
  than letting Tally invent them.
* **``REMOTEID`` is what makes a re-import safe.** With a stable id Tally
  updates the existing voucher instead of adding a second copy, which matters
  because "export again after fixing three classifications" is the normal case,
  not the exception.

Everything is escaped through :mod:`xml.etree`, never string-formatted. A payee
name containing ``&`` is not exotic -- ``BRN-CLG-CHQ PAID TO Wipro Ge
Health/HONGKONG and S`` is one ``&`` away from it in the sample data -- and a
hand-built XML string breaks on the first one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from core.money import format_inr, to_rupees
from ledger.vouchers import Voucher, build_voucher, ledger_master_group


@dataclass(frozen=True)
class ExportResult:
    xml: str
    voucher_count: int
    ledger_count: int
    #: Rows left out because nobody has classified them yet. Reported rather
    #: than raised: a firm exporting nine tenths of a statement while three rows
    #: wait on a client's answer is a normal Tuesday.
    skipped: tuple[str, ...] = ()


def export_statement(statement, *, company_name: str, include_masters: bool = True) -> ExportResult:
    """Render every classified row of ``statement`` as Tally XML."""
    classifications = (
        statement.transactions.select_related(
            "classification__ledger", "bank_account"
        )
        .filter(classification__isnull=False)
        .order_by("value_date", "row_number")
    )

    vouchers = []
    skipped = []
    ledgers = {}

    for transaction in classifications:
        classification = transaction.classification
        if classification.ledger is None:
            skipped.append(
                f"{transaction.value_date:%d-%m-%Y} "
                f"{format_inr(transaction.amount_paise)} {transaction.narration[:50]}"
            )
            continue
        vouchers.append(build_voucher(classification))
        ledgers[classification.ledger.name] = classification.ledger.group

    bank = statement.bank_account
    ledgers.setdefault(bank.ledger_name, "BANK")

    return ExportResult(
        xml=render(
            vouchers,
            company_name=company_name,
            ledgers=ledgers if include_masters else {},
        ),
        voucher_count=len(vouchers),
        ledger_count=len(ledgers) if include_masters else 0,
        skipped=tuple(skipped),
    )


def render(vouchers, *, company_name: str, ledgers: dict[str, str] | None = None) -> str:
    """Build the ENVELOPE document for ``vouchers`` and their ledger masters."""
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
    # a ledger defined later in the same file would create it under the default
    # group before reaching its real definition.
    for name, group in sorted((ledgers or {}).items()):
        _append_ledger_master(request_data, name, group)

    for voucher in vouchers:
        _append_voucher(request_data, voucher)

    return _pretty(envelope)


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


def _append_voucher(parent, voucher: Voucher) -> None:
    message = ET.SubElement(parent, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
    node = ET.SubElement(
        message,
        "VOUCHER",
        {
            "REMOTEID": voucher.remote_id,
            "VCHTYPE": voucher.voucher_type,
            "ACTION": "Create",
            "OBJVIEW": "Accounting Voucher View",
        },
    )

    ET.SubElement(node, "DATE").text = voucher.date
    ET.SubElement(node, "EFFECTIVEDATE").text = voucher.date
    ET.SubElement(node, "VOUCHERTYPENAME").text = voucher.voucher_type
    ET.SubElement(node, "PARTYLEDGERNAME").text = voucher.party_ledger
    ET.SubElement(node, "NARRATION").text = voucher.narration
    if voucher.reference:
        ET.SubElement(node, "REFERENCE").text = voucher.reference
    ET.SubElement(node, "PERSISTEDVIEW").text = "Accounting Voucher View"

    for line in voucher.lines:
        entry = ET.SubElement(node, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(entry, "LEDGERNAME").text = line.ledger_name
        ET.SubElement(entry, "ISDEEMEDPOSITIVE").text = line.is_deemed_positive
        ET.SubElement(entry, "AMOUNT").text = _amount(line.amount_paise)


def _amount(paise: int) -> str:
    """Rupees with two decimals -- Tally's wire format, and the only place the
    ledger leaves paise. Exact, because the conversion is a Decimal divide by
    100 rather than a float one."""
    return f"{to_rupees(paise):.2f}"


def _pretty(element) -> str:
    """Indented XML. Tally does not care; the person diffing two exports does."""
    ET.indent(element, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(element, encoding="unicode")
